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
RESOURCE_TYPES = {"module", "css"}


class DeploymentError(RuntimeError):
    """A safe, user-facing deployment failure."""


class CommandRejectedError(DeploymentError):
    """Home Assistant definitively rejected a correlated command."""


class AmbiguousCommandError(DeploymentError):
    """A command may have committed before its outcome became unavailable."""


def _redact(message, *secrets):
    safe_message = str(message)
    for secret in secrets:
        if secret:
            safe_message = safe_message.replace(str(secret), "[redacted]")
    return safe_message


def make_ws_url(base_url):
    """Convert an HTTP(S) Home Assistant base URL to its WebSocket URL."""
    error_message = "Home Assistant URL must be a valid http or https URL"
    try:
        parsed = urllib_parse.urlsplit(base_url)
        hostname = parsed.hostname
        parsed.port
    except (TypeError, UnicodeError, ValueError):
        raise DeploymentError(error_message) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or any(character.isspace() for character in parsed.netloc)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DeploymentError(error_message)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/api/websocket"
    return urllib_parse.urlunsplit((scheme, parsed.netloc, path, "", ""))


def _validate_resource_requirements(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("invalid resource requirements")
    requirements = []
    seen = set()
    for requirement in value:
        if not isinstance(requirement, dict) or set(requirement) != {"type", "url_suffix"}:
            raise ValueError("invalid resource requirement")
        resource_type = requirement["type"]
        suffix = requirement["url_suffix"]
        if type(resource_type) is not str or resource_type not in RESOURCE_TYPES:
            raise ValueError("invalid resource type")
        if type(suffix) is not str or not suffix.startswith("/") or suffix.startswith("//"):
            raise ValueError("invalid resource suffix")
        parsed = urllib_parse.urlsplit(suffix)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path != suffix:
            raise ValueError("invalid resource suffix")
        key = (resource_type, suffix)
        if key in seen:
            raise ValueError("duplicate resource requirement")
        seen.add(key)
        requirements.append({"type": resource_type, "url_suffix": suffix})
    return requirements


def load_manifest(root, manifest_path):
    """Load validated resource requirements and ordered dashboard entries."""
    try:
        root = Path(root).resolve()
        manifest_path = Path(manifest_path)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        manifest_path = manifest_path.resolve()
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = yaml.safe_load(manifest_file)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("dashboards"), list):
            raise ValueError("invalid manifest structure")
        resource_requirements = _validate_resource_requirements(
            manifest.get("resource_requirements")
        )
        entries = []
        for manifest_entry in manifest["dashboards"]:
            if not isinstance(manifest_entry, dict):
                raise ValueError("invalid dashboard entry")
            entry = dict(manifest_entry)
            string_fields = ("url_path", "title", "icon", "mode", "config")
            if any(
                type(entry.get(field)) is not str or not entry[field].strip()
                for field in string_fields
            ):
                raise ValueError("invalid dashboard string field")
            if entry["mode"] != "storage":
                raise ValueError("dashboard mode must be storage")
            for field in ("show_in_sidebar", "require_admin"):
                if type(entry.get(field)) is not bool:
                    raise ValueError("invalid dashboard boolean field")
            config_path = (root / entry["config"]).resolve()
            config_path.relative_to(root)
            with config_path.open(encoding="utf-8") as config_file:
                entry["config_data"] = yaml.safe_load(config_file)
            if not isinstance(entry["config_data"], dict):
                raise ValueError("dashboard config must be a mapping")
            entries.append(entry)
        return {
            "entries": entries,
            "resource_requirements": resource_requirements,
        }
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        raise DeploymentError("Unable to load dashboard manifest or config YAML") from None


def load_entries(root, manifest_path):
    """Load ordered dashboard entries for compatibility with existing callers."""
    return load_manifest(root, manifest_path)["entries"]


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
        self.warnings = []

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
            try:
                self.close()
            except DeploymentError as close_error:
                self.warnings.append(str(close_error))
            if isinstance(exc, DeploymentError):
                raise
            raise DeploymentError(
                _redact("Unable to connect to Home Assistant WebSocket", self.token)
            ) from None

    def close(self):
        if self.connection is not None:
            connection = self.connection
            self.connection = None
            try:
                connection.close()
            except Exception:
                raise DeploymentError("Failed to close Home Assistant WebSocket") from None

    def __exit__(self, exc_type, _exc_value, _traceback):
        try:
            self.close()
        except DeploymentError as close_error:
            self.warnings.append(str(close_error))
        return False

    def command(self, payload):
        command_name = payload.get("type", "unknown")
        command_id = self.next_id
        self.next_id += 1
        message = dict(payload)
        message["id"] = command_id
        try:
            encoded_message = json.dumps(message)
        except Exception:
            raise DeploymentError(
                f"Home Assistant command {command_name} could not be encoded"
            ) from None
        try:
            self.connection.send(encoded_message)
        except Exception:
            raise AmbiguousCommandError(
                f"Home Assistant command {command_name} send failed; outcome is unknown"
            ) from None
        try:
            while True:
                response = self._receive()
                if response.get("id") == command_id:
                    break
        except Exception:
            raise AmbiguousCommandError(
                f"Home Assistant command {command_name} response was lost; outcome is unknown"
            ) from None
        if response.get("type") != "result":
            raise AmbiguousCommandError(
                f"Home Assistant command {command_name} returned an invalid result; "
                + "outcome is unknown"
            )
        if response.get("success") is False:
            error = response.get("error") or {}
            if not isinstance(error, dict):
                error = {}
            code = _redact(error.get("code", "unknown_error"), self.token)
            detail = _redact(error.get("message", "command failed"), self.token)
            raise CommandRejectedError(
                f"Home Assistant command {command_name} failed: {code}: {detail}"
            )
        if response.get("success") is not True or "result" not in response:
            raise AmbiguousCommandError(
                f"Home Assistant command {command_name} returned an incomplete result; "
                + "outcome is unknown"
            )
        return response.get("result")


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file_pointer, _code, _message, _headers, _new_url):
        return None


def http_resource_status(base_url, token, path):
    """Return whether an authenticated frontend resource is available."""
    url = base_url.rstrip("/") + path
    request = urllib_request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    opener = urllib_request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=10) as response:
            return 200 <= response.status < 300
    except urllib_error.HTTPError:
        return False
    except (urllib_error.URLError, OSError):
        raise DeploymentError(
            _redact(f"Unable to verify frontend resource {path}", token)
        ) from None


def _resolve_registered_resource(resources, requirement):
    suffix = requirement["url_suffix"]
    resource_type = requirement["type"]
    if not isinstance(resources, list):
        raise DeploymentError(f"Invalid frontend resource registry for {suffix}")
    matches = []
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("type") != resource_type:
            continue
        registered_url = resource.get("url")
        try:
            parsed = urllib_parse.urlsplit(registered_url)
        except (TypeError, UnicodeError, ValueError):
            continue
        if type(registered_url) is not str or not parsed.path.endswith(suffix):
            continue
        unsafe = (
            not registered_url
            or not registered_url.startswith("/")
            or registered_url.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        )
        if unsafe:
            raise DeploymentError(f"Unsafe registered frontend resource for {suffix}")
        matches.append(registered_url)
    if len(matches) != 1:
        raise DeploymentError(
            f"Expected exactly one registered frontend resource for {suffix}"
        )
    return matches[0]


def preflight(
    client,
    base_url,
    token,
    entries,
    resource_checker=http_resource_status,
    resource_requirements=(),
):
    """Validate collision, entity, and resource prerequisites without mutation."""
    target_paths = [entry["url_path"] for entry in entries]
    duplicate_paths = sorted(
        {target_path for target_path in target_paths if target_paths.count(target_path) > 1}
    )
    if duplicate_paths:
        raise DeploymentError(
            "Duplicate target dashboard URL path: " + ", ".join(duplicate_paths)
        )

    original_dashboards = client.command({"type": "lovelace/dashboards/list"})
    existing_paths = {dashboard.get("url_path") for dashboard in original_dashboards}
    collisions = sorted(set(target_paths).intersection(existing_paths))
    if collisions:
        raise DeploymentError(
            "Target dashboard URL path already exists: " + ", ".join(collisions)
        )

    panels = client.command({"type": "get_panels"})
    if not isinstance(panels, dict):
        raise DeploymentError("Home Assistant returned an invalid panel registry")
    panel_paths = {str(panel_key).lstrip("/") for panel_key in panels}
    panel_paths.update(
        str(panel["url_path"]).lstrip("/")
        for panel in panels.values()
        if isinstance(panel, dict) and isinstance(panel.get("url_path"), str)
    )
    panel_collisions = sorted(set(target_paths).intersection(panel_paths))
    if panel_collisions:
        raise DeploymentError(
            "Target dashboard URL path collides with panel: "
            + ", ".join(panel_collisions)
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

    if resource_requirements:
        registered_resources = client.command({"type": "lovelace/resources"})
        for requirement in resource_requirements:
            suffix = requirement["url_suffix"]
            registered_url = _resolve_registered_resource(
                registered_resources, requirement
            )
            try:
                available = resource_checker(base_url, token, registered_url)
            except Exception:
                raise DeploymentError(
                    f"Unable to verify required frontend resource {suffix}"
                ) from None
            if not available:
                raise DeploymentError(
                    f"Missing required frontend resource {suffix}"
                )

    return {
        "status": "ready",
        "original_dashboards": original_dashboards,
        "target_paths": target_paths,
        "verified_entities": sorted(required_entities),
        "verified_resources": list(REQUIRED_RESOURCES),
        "verified_resource_requirements": [
            dict(requirement) for requirement in resource_requirements
        ],
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
    except (OSError, TypeError, ValueError):
        raise DeploymentError(f"Unable to write deployment artifact {path.name}") from None


def deploy(client, entries, preflight_report, artifact_dir):
    """Create, save, and verify dashboards, rolling back created IDs on failure."""
    artifact_dir = Path(artifact_dir)
    original_dashboards = preflight_report["original_dashboards"]
    write_json(
        artifact_dir / "pre-deploy-dashboard-registry.json",
        original_dashboards,
    )

    created = []
    attempted = []
    ambiguous_creates = []
    operation = "dashboard deployment"
    try:
        for entry in entries:
            url_path = entry["url_path"]
            operation = f"create dashboard {url_path}"
            expected_dashboard = {
                "url_path": url_path,
                "title": entry["title"],
                "icon": entry["icon"],
                "mode": entry["mode"],
                "show_in_sidebar": entry["show_in_sidebar"],
                "require_admin": entry["require_admin"],
            }
            attempted.append(expected_dashboard)
            try:
                dashboard = client.command(
                    {
                        "type": "lovelace/dashboards/create",
                        **expected_dashboard,
                    }
                )
            except AmbiguousCommandError:
                ambiguous_creates.append(expected_dashboard)
                raise
            if not isinstance(dashboard, dict) or not dashboard.get("id"):
                ambiguous_creates.append(expected_dashboard)
                raise AmbiguousCommandError("Dashboard creation returned no dashboard ID")
            created.append(dashboard)
            if any(
                dashboard.get(field) != expected_value
                for field, expected_value in expected_dashboard.items()
            ):
                raise DeploymentError(f"Created dashboard metadata differs for {url_path}")

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
        for created_dashboard in created:
            dashboard_id = created_dashboard["id"]
            if final_by_id.get(dashboard_id) != created_dashboard:
                raise DeploymentError(
                    "Created dashboard missing or changed: "
                    + f"{dashboard_id} ({created_dashboard.get('url_path', 'unknown')})"
                )
        result = {
            "status": "deployed",
            "created": created,
            "final_dashboards": final_dashboards,
        }
        write_json(artifact_dir / "deployment-result.json", result)
        return result
    except Exception as exc:
        error_message = f"Deployment failed during {operation}"
        if isinstance(exc, DeploymentError):
            error_message += f": {exc}"
        else:
            error_message += ": unexpected internal error"
        deleted_dashboard_ids = []
        rollback_errors = []
        original_ids = {
            dashboard.get("id") for dashboard in original_dashboards if dashboard.get("id")
        }
        attempted_by_path = {
            expected_dashboard["url_path"]: expected_dashboard
            for expected_dashboard in attempted
        }
        ambiguous_by_path = {
            expected_dashboard["url_path"]: attempted_by_path[expected_dashboard["url_path"]]
            for expected_dashboard in ambiguous_creates
        }
        ambiguous_paths = list(ambiguous_by_path)
        rollback_candidates = {}
        for dashboard in created:
            dashboard_id = dashboard.get("id")
            if dashboard_id and dashboard_id not in original_ids:
                rollback_candidates[dashboard_id] = dashboard
        if ambiguous_by_path:
            try:
                reconciled_dashboards = client.command({"type": "lovelace/dashboards/list"})
                reconciled_ambiguous_paths = set()
                manual_reconciliation_paths = set()
                for dashboard in reconciled_dashboards:
                    dashboard_id = dashboard.get("id")
                    url_path = dashboard.get("url_path")
                    if url_path not in ambiguous_by_path or dashboard_id in original_ids:
                        continue
                    if dashboard_id in rollback_candidates:
                        continue
                    expected_dashboard = ambiguous_by_path[url_path]
                    metadata_matches = all(
                        dashboard.get(field) == expected_value
                        for field, expected_value in expected_dashboard.items()
                    )
                    if not metadata_matches:
                        rollback_errors.append(
                            "Dashboard metadata did not match attempted path "
                            + f"{url_path}; manual reconciliation needed"
                        )
                        manual_reconciliation_paths.add(url_path)
                        continue
                    reconciled_ambiguous_paths.add(url_path)
                    if not dashboard_id:
                        rollback_errors.append(
                            "Cannot delete reconciled dashboard without ID at attempted path "
                            + f"{url_path}; manual reconciliation needed"
                        )
                        continue
                    rollback_candidates[dashboard_id] = dashboard
                for ambiguous_path in ambiguous_paths:
                    if (
                        ambiguous_path not in reconciled_ambiguous_paths
                        and ambiguous_path not in manual_reconciliation_paths
                    ):
                        rollback_errors.append(
                            "No exact dashboard metadata match for ambiguous path "
                            + f"{ambiguous_path}; manual reconciliation needed"
                        )
            except Exception:
                rollback_errors.append("Failed to reconcile dashboard registry during rollback")

        ordered_candidates = []
        ordered_candidate_ids = set()
        candidate_values = list(rollback_candidates.values())
        for target_path in reversed(ambiguous_paths):
            for dashboard in reversed(candidate_values):
                if dashboard.get("url_path") == target_path:
                    ordered_candidates.append(dashboard)
                    ordered_candidate_ids.add(dashboard["id"])
        for dashboard in reversed(created):
            if (
                dashboard.get("id") in rollback_candidates
                and dashboard["id"] not in ordered_candidate_ids
            ):
                ordered_candidates.append(rollback_candidates[dashboard["id"]])
                ordered_candidate_ids.add(dashboard["id"])
        for dashboard in ordered_candidates:
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
        manifest = load_manifest(root, args.manifest)
        entries = manifest["entries"]
        resource_requirements = manifest["resource_requirements"]
        with HomeAssistantWebSocket(args.base_url, token) as client:
            report = preflight(
                client,
                args.base_url,
                token,
                entries,
                resource_requirements=resource_requirements,
            )
            write_json(artifact_dir / "preflight.json", report)
            if args.apply:
                result = deploy(client, entries, report, artifact_dir)
            else:
                result = dict(report)
                result["status"] = "dry-run"
        result["warnings"] = list(getattr(client, "warnings", []))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except DeploymentError as exc:
        print(f"Deployment failed: {_redact(exc, token)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
