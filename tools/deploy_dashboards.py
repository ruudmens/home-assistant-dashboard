#!/usr/bin/env python3
"""Preflight and atomically deploy storage-mode Home Assistant dashboards."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import websocket
import yaml


ENTITY_ID = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
REQUIRED_RESOURCES = (
    "/hacsfiles/button-card/button-card.js",
    "/hacsfiles/lovelace-card-mod/card-mod.js",
    "/hacsfiles/stack-in-card/stack-in-card.js",
)


class DeploymentError(RuntimeError):
    """A safe, user-facing deployment failure."""


def _redact(message, *secrets):
    safe_message = str(message)
    for secret in secrets:
        if secret:
            safe_message = safe_message.replace(str(secret), "[redacted]")
    return safe_message


def make_ws_url(base_url):
    """Convert an HTTP(S) Home Assistant base URL to its WebSocket URL."""
    parsed = urllib_parse.urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DeploymentError("Home Assistant URL must be a valid http or https URL")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/api/websocket"
    return urllib_parse.urlunsplit((scheme, parsed.netloc, path, "", ""))


def load_entries(root, manifest_path):
    """Load the ordered manifest entries and their YAML dashboard configs."""
    root = Path(root)
    manifest_path = Path(manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    try:
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = yaml.safe_load(manifest_file)
        entries = []
        for manifest_entry in manifest["dashboards"]:
            entry = dict(manifest_entry)
            config_path = root / entry["config"]
            with config_path.open(encoding="utf-8") as config_file:
                entry["config_data"] = yaml.safe_load(config_file)
            entries.append(entry)
        return entries
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise DeploymentError("Unable to load dashboard manifest or config YAML") from exc


def collect_entity_ids(value):
    """Recursively collect entity-id-shaped scalar values from a config."""
    entity_ids = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"perform_action", "service"}:
                continue
            entity_ids.update(collect_entity_ids(child))
    elif isinstance(value, list):
        for child in value:
            entity_ids.update(collect_entity_ids(child))
    elif isinstance(value, str) and ENTITY_ID.fullmatch(value):
        entity_ids.add(value)
    return entity_ids


class HomeAssistantWebSocket:
    """Authenticated synchronous client for Home Assistant WebSocket commands."""

    def __init__(self, base_url, token, timeout=10):
        self.ws_url = make_ws_url(base_url)
        self.token = token
        self.timeout = timeout
        self.connection = None
        self.next_id = 1

    def _receive(self):
        try:
            return json.loads(self.connection.recv())
        except Exception:
            raise DeploymentError(
                _redact("Invalid or unavailable Home Assistant WebSocket response", self.token)
            ) from None

    def __enter__(self):
        try:
            self.connection = websocket.create_connection(self.ws_url, timeout=self.timeout)
            auth_required = self._receive()
            if auth_required.get("type") != "auth_required":
                raise DeploymentError("Home Assistant did not request WebSocket authentication")
            self.connection.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_result = self._receive()
            if auth_result.get("type") != "auth_ok":
                raise DeploymentError("Home Assistant WebSocket authentication failed")
            return self
        except Exception as exc:
            self.close()
            if isinstance(exc, DeploymentError):
                raise
            raise DeploymentError(
                _redact("Unable to connect to Home Assistant WebSocket", self.token)
            ) from None

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()
        return False

    def command(self, payload):
        command_name = payload.get("type", "unknown")
        command_id = self.next_id
        self.next_id += 1
        message = dict(payload)
        message["id"] = command_id
        try:
            self.connection.send(json.dumps(message))
            while True:
                response = self._receive()
                if response.get("id") == command_id:
                    break
        except DeploymentError:
            raise
        except Exception:
            raise DeploymentError(f"Home Assistant command {command_name} failed") from None
        if response.get("type") != "result":
            raise DeploymentError(f"Home Assistant command {command_name} returned no result")
        if not response.get("success"):
            error = response.get("error") or {}
            code = _redact(error.get("code", "unknown_error"), self.token)
            detail = _redact(error.get("message", "command failed"), self.token)
            raise DeploymentError(
                f"Home Assistant command {command_name} failed: {code}: {detail}"
            )
        return response.get("result")


def http_resource_status(base_url, token, path):
    """Return whether an authenticated frontend resource is available."""
    url = base_url.rstrip("/") + path
    request = urllib_request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 400
    except urllib_error.HTTPError as exc:
        return 300 <= exc.code < 400
    except (urllib_error.URLError, OSError):
        raise DeploymentError(
            _redact(f"Unable to verify frontend resource {path}", token)
        ) from None


def preflight(client, base_url, token, entries, resource_checker=http_resource_status):
    """Validate collision, entity, and resource prerequisites without mutation."""
    original_dashboards = client.command({"type": "lovelace/dashboards/list"})
    target_paths = [entry["url_path"] for entry in entries]
    existing_paths = {dashboard.get("url_path") for dashboard in original_dashboards}
    collisions = sorted(set(target_paths).intersection(existing_paths))
    if collisions:
        raise DeploymentError(
            "Target dashboard URL path already exists: " + ", ".join(collisions)
        )

    states = client.command({"type": "get_states"})
    live_entities = {
        state.get("entity_id") for state in states if isinstance(state.get("entity_id"), str)
    }
    required_entities = set()
    for entry in entries:
        required_entities.update(collect_entity_ids(entry["config_data"]))
    missing_entities = sorted(required_entities - live_entities)
    if missing_entities:
        raise DeploymentError("Missing Home Assistant entities: " + ", ".join(missing_entities))

    missing_resources = [
        path for path in REQUIRED_RESOURCES if not resource_checker(base_url, token, path)
    ]
    if missing_resources:
        raise DeploymentError("Missing frontend resources: " + ", ".join(missing_resources))

    return {
        "status": "ready",
        "original_dashboards": original_dashboards,
        "target_paths": target_paths,
        "verified_entities": sorted(required_entities),
        "verified_resources": list(REQUIRED_RESOURCES),
    }


def write_json(path, value):
    """Write stable, human-readable UTF-8 JSON."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise DeploymentError(f"Unable to write deployment artifact {path.name}") from exc


def deploy(client, entries, preflight_report, artifact_dir):
    """Create, save, and verify dashboards, rolling back created IDs on failure."""
    artifact_dir = Path(artifact_dir)
    original_dashboards = preflight_report["original_dashboards"]
    write_json(
        artifact_dir / "pre-deploy-dashboard-registry.json",
        original_dashboards,
    )

    created = []
    operation = "dashboard deployment"
    try:
        for entry in entries:
            url_path = entry["url_path"]
            operation = f"create dashboard {url_path}"
            dashboard = client.command(
                {
                    "type": "lovelace/dashboards/create",
                    "url_path": url_path,
                    "title": entry["title"],
                    "icon": entry["icon"],
                    "mode": entry["mode"],
                    "show_in_sidebar": entry["show_in_sidebar"],
                    "require_admin": entry["require_admin"],
                }
            )
            if not isinstance(dashboard, dict) or not dashboard.get("id"):
                raise DeploymentError("Dashboard creation returned no dashboard ID")
            created.append(dashboard)

            operation = f"save dashboard config {url_path}"
            client.command(
                {
                    "type": "lovelace/config/save",
                    "url_path": url_path,
                    "config": entry["config_data"],
                }
            )
            operation = f"verify dashboard config {url_path}"
            saved_config = client.command(
                {
                    "type": "lovelace/config",
                    "url_path": url_path,
                    "force": True,
                }
            )
            if saved_config != entry["config_data"]:
                raise DeploymentError(f"Saved dashboard config differs for {url_path}")

        operation = "verify final dashboard registry"
        final_dashboards = client.command({"type": "lovelace/dashboards/list"})
        final_by_id = {dashboard.get("id"): dashboard for dashboard in final_dashboards}
        for original in original_dashboards:
            if final_by_id.get(original.get("id")) != original:
                raise DeploymentError(
                    f"Pre-existing dashboard changed: {original.get('id', 'unknown')}"
                )
        result = {
            "status": "deployed",
            "created": created,
            "final_dashboards": final_dashboards,
        }
        write_json(artifact_dir / "deployment-result.json", result)
        return result
    except Exception:
        error_message = f"Deployment failed during {operation}"
        deleted_dashboard_ids = []
        rollback_errors = []
        for dashboard in reversed(created):
            dashboard_id = dashboard["id"]
            try:
                client.command(
                    {
                        "type": "lovelace/dashboards/delete",
                        "dashboard_id": dashboard_id,
                    }
                )
                deleted_dashboard_ids.append(dashboard_id)
            except Exception:
                rollback_errors.append(f"Failed to delete dashboard {dashboard_id} during rollback")
        status = "rollback_incomplete" if rollback_errors else "rolled_back"
        if rollback_errors:
            error_message += "; rollback incomplete: " + "; ".join(rollback_errors)
        failure = {
            "status": status,
            "error": error_message,
            "deleted_dashboard_ids": deleted_dashboard_ids,
            "rollback_errors": rollback_errors,
        }
        write_json(artifact_dir / "deployment-failure.json", failure)
        raise DeploymentError(error_message) from None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("HA_URL"))
    parser.add_argument("--token-env", default="HA_TOKEN")
    parser.add_argument("--manifest", default="tools/dashboard_manifest.yaml")
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get(args.token_env)
    if not args.base_url or not token:
        print(
            f"Home Assistant URL and token environment variable {args.token_env} are required",
            file=sys.stderr,
        )
        return 2

    root = Path(__file__).resolve().parents[1]
    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.is_absolute():
        artifact_dir = root / artifact_dir
    try:
        entries = load_entries(root, args.manifest)
        with HomeAssistantWebSocket(args.base_url, token) as client:
            report = preflight(client, args.base_url, token, entries)
            write_json(artifact_dir / "preflight.json", report)
            if args.apply:
                result = deploy(client, entries, report, artifact_dir)
            else:
                result = dict(report)
                result["status"] = "dry-run"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except DeploymentError as exc:
        print(f"Deployment failed: {_redact(exc, token)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
