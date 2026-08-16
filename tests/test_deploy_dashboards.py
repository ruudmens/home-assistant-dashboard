"""Tests for the Home Assistant dashboard deployment client."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib import error as urllib_error

from tools import deploy_dashboards


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "dashboard_manifest.yaml"
TOKEN = "super-secret-test-token"


class FakeClient:
    """Small in-memory model of the Lovelace WebSocket commands we use."""

    def __init__(
        self,
        entries,
        *,
        collision=False,
        missing_entity=None,
        fail_save=None,
        fail_delete=None,
    ):
        self.entries = entries
        self.original = {
            "id": "overview",
            "url_path": "lovelace",
            "title": "Overview",
            "icon": "mdi:view-dashboard",
            "mode": "storage",
            "show_in_sidebar": True,
            "require_admin": False,
        }
        self.dashboards = [dict(self.original)]
        if collision:
            self.dashboards.append(
                {
                    "id": "existing-luxury-home",
                    "url_path": entries[0]["url_path"],
                    "title": "Existing",
                }
            )
        entities = set()
        for entry in entries:
            entities.update(deploy_dashboards.collect_entity_ids(entry["config_data"]))
        if missing_entity:
            entities.remove(missing_entity)
        self.states = [{"entity_id": entity_id} for entity_id in sorted(entities)]
        self.fail_save = fail_save
        self.fail_delete = fail_delete
        self.commands = []
        self.configs = {}
        self.deleted = []

    def command(self, payload):
        self.commands.append(dict(payload))
        command_type = payload["type"]
        if command_type == "lovelace/dashboards/list":
            return [dict(dashboard) for dashboard in self.dashboards]
        if command_type == "get_states":
            return list(self.states)
        if command_type == "lovelace/dashboards/create":
            dashboard = dict(payload)
            dashboard.pop("type")
            dashboard["id"] = f'{payload["url_path"]}-id'
            self.dashboards.append(dashboard)
            return dict(dashboard)
        if command_type == "lovelace/config/save":
            if payload["url_path"] == self.fail_save:
                raise deploy_dashboards.DeploymentError(
                    f"save failed for {payload['url_path']} with {TOKEN}"
                )
            self.configs[payload["url_path"]] = payload["config"]
            return None
        if command_type == "lovelace/config":
            return self.configs[payload["url_path"]]
        if command_type == "lovelace/dashboards/delete":
            dashboard_id = payload["dashboard_id"]
            if dashboard_id == self.fail_delete:
                raise deploy_dashboards.DeploymentError(
                    f"rollback refused for {dashboard_id}; {TOKEN}"
                )
            self.deleted.append(dashboard_id)
            self.dashboards = [
                dashboard
                for dashboard in self.dashboards
                if dashboard.get("id") != dashboard_id
            ]
            return None
        raise AssertionError(f"Unexpected command: {payload}")


class FakeConnection:
    def __init__(self, messages, close_error=None):
        self.messages = [json.dumps(message) for message in messages]
        self.sent = []
        self.closed = False
        self.close_error = close_error

    def recv(self):
        return self.messages.pop(0)

    def send(self, message):
        self.sent.append(json.loads(message))

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = deploy_dashboards.load_entries(ROOT, MANIFEST)

    def test_load_entries_preserves_manifest_order_and_loads_yaml(self):
        self.assertEqual(
            [entry["url_path"] for entry in self.entries],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )
        self.assertTrue(all(isinstance(entry["config_data"], dict) for entry in self.entries))
        self.assertEqual(self.entries[0]["config_data"]["title"], "Luxury Home")

    def test_make_ws_url_converts_http_schemes(self):
        self.assertEqual(
            deploy_dashboards.make_ws_url("https://ha.example.test/"),
            "wss://ha.example.test/api/websocket",
        )
        self.assertEqual(
            deploy_dashboards.make_ws_url("http://192.0.2.10:8123"),
            "ws://192.0.2.10:8123/api/websocket",
        )

    def test_make_ws_url_rejects_invalid_urls(self):
        for value in ("ftp://ha.example.test", "ha.example.test", "https:///missing-host"):
            with self.subTest(value=value), self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.make_ws_url(value)

    def test_make_ws_url_wraps_unclosed_ipv6_address(self):
        with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
            deploy_dashboards.make_ws_url("http://[::1")
        self.assertIsNone(raised.exception.__cause__)

    def test_make_ws_url_rejects_non_numeric_port(self):
        with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
            deploy_dashboards.make_ws_url("https://ha.example.test:notaport")
        self.assertIsNone(raised.exception.__cause__)

    def test_collect_entity_ids_catches_camera_image_and_skips_service_values(self):
        config = {
            "camera_image": "camera.front_door",
            "mixed": ["light.kitchen", {"entity_id": "sensor.temperature"}, 7],
            "tap_action": {
                "perform_action": "scene.turn_on",
                "service": "switch.turn_on",
                "target": {"entity_id": "scene.evening"},
            },
        }
        self.assertEqual(
            deploy_dashboards.collect_entity_ids(config),
            {"camera.front_door", "light.kitchen", "sensor.temperature", "scene.evening"},
        )

    def test_preflight_stops_on_target_collision_before_mutation(self):
        client = FakeClient(self.entries, collision=True)
        with self.assertRaisesRegex(deploy_dashboards.DeploymentError, "luxury-home"):
            deploy_dashboards.preflight(
                client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
            )
        self.assertEqual(
            [command["type"] for command in client.commands],
            ["lovelace/dashboards/list"],
        )

    def test_preflight_reports_sorted_missing_live_entities(self):
        client = FakeClient(self.entries, missing_entity="light.garage_2")
        with self.assertRaisesRegex(deploy_dashboards.DeploymentError, "light.garage_2"):
            deploy_dashboards.preflight(
                client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
            )
        self.assertFalse(any(command["type"].endswith("/create") for command in client.commands))

    def test_preflight_requires_every_frontend_resource(self):
        client = FakeClient(self.entries)

        def resource_checker(_base_url, _token, path):
            return path != "/hacsfiles/stack-in-card/stack-in-card.js"

        with self.assertRaisesRegex(deploy_dashboards.DeploymentError, "stack-in-card"):
            deploy_dashboards.preflight(
                client, "https://ha.example.test", TOKEN, self.entries, resource_checker
            )

    def test_successful_deploy_preserves_original_and_writes_safe_artifacts(self):
        client = FakeClient(self.entries)
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_dir = Path(temp_dir)
            result = deploy_dashboards.deploy(client, self.entries, report, artifact_dir)

            creates = [
                command for command in client.commands if command["type"] == "lovelace/dashboards/create"
            ]
            saves = [
                command for command in client.commands if command["type"] == "lovelace/config/save"
            ]
            reads = [
                command for command in client.commands if command["type"] == "lovelace/config"
            ]
            expected_order = ["luxury-home", "luxury-garage", "luxury-remote"]
            self.assertEqual([command["url_path"] for command in creates], expected_order)
            self.assertEqual([command["url_path"] for command in saves], expected_order)
            self.assertEqual([command["url_path"] for command in reads], expected_order)
            self.assertTrue(all(command["force"] is True for command in reads))
            self.assertEqual(client.dashboards[0], client.original)
            self.assertEqual(client.deleted, [])
            self.assertEqual(result["status"], "deployed")
            self.assertTrue((artifact_dir / "pre-deploy-dashboard-registry.json").is_file())
            self.assertTrue((artifact_dir / "deployment-result.json").is_file())
            serialized = "\n".join(path.read_text(encoding="utf-8") for path in artifact_dir.iterdir())
            for secret in (TOKEN, "Bearer", "access_token"):
                self.assertNotIn(secret, serialized)

    def test_save_failure_rolls_back_only_created_dashboards_in_reverse_order(self):
        client = FakeClient(self.entries, fail_save="luxury-garage")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(client.deleted, ["luxury-garage-id", "luxury-home-id"])
            self.assertEqual(client.dashboards, [client.original])
            self.assertEqual(failure["status"], "rolled_back")
            self.assertEqual(
                failure["deleted_dashboard_ids"],
                ["luxury-garage-id", "luxury-home-id"],
            )
            self.assertNotIn(TOKEN, json.dumps(failure))

    def test_rollback_failure_is_reported_and_does_not_expose_secrets(self):
        client = FakeClient(
            self.entries,
            fail_save="luxury-garage",
            fail_delete="luxury-garage-id",
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError, "rollback.*luxury-garage-id"
            ) as raised:
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure_text = (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            failure = json.loads(failure_text)
            self.assertEqual(failure["status"], "rollback_incomplete")
            self.assertTrue(failure["rollback_errors"])
            self.assertEqual(client.deleted, ["luxury-home-id"])
            self.assertNotIn(TOKEN, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertNotIn(TOKEN, failure_text)


class HttpResourceTests(unittest.TestCase):
    def test_http_resource_status_accepts_three_hundred_responses(self):
        response = urllib_error.HTTPError(
            "https://ha.example.test/resource.js", 304, "Not Modified", {}, None
        )
        with mock.patch.object(
            deploy_dashboards.urllib_request, "urlopen", side_effect=response
        ):
            self.assertTrue(
                deploy_dashboards.http_resource_status(
                    "https://ha.example.test", TOKEN, "/resource.js"
                )
            )

    def test_http_resource_status_rejects_http_error(self):
        response = urllib_error.HTTPError(
            "https://ha.example.test/resource.js", 404, "Not Found", {}, None
        )
        with mock.patch.object(
            deploy_dashboards.urllib_request, "urlopen", side_effect=response
        ):
            self.assertFalse(
                deploy_dashboards.http_resource_status(
                    "https://ha.example.test", TOKEN, "/resource.js"
                )
            )

    def test_http_resource_network_error_does_not_expose_token(self):
        with mock.patch.object(
            deploy_dashboards.urllib_request,
            "urlopen",
            side_effect=urllib_error.URLError(f"network rejected {TOKEN}"),
        ):
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                deploy_dashboards.http_resource_status(
                    "https://ha.example.test", TOKEN, "/resource.js"
                )
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)


class WebSocketTests(unittest.TestCase):
    def test_authenticates_and_correlates_monotonic_command_ids(self):
        connection = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok", "ha_version": "2026.8.0"},
                {"id": 999, "type": "result", "success": True, "result": "unrelated"},
                {"id": 1, "type": "result", "success": True, "result": ["one"]},
                {"id": 2, "type": "result", "success": True, "result": ["two"]},
            ]
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ) as create_connection:
            with deploy_dashboards.HomeAssistantWebSocket(
                "https://ha.example.test/", TOKEN, timeout=4
            ) as client:
                self.assertEqual(client.command({"type": "first"}), ["one"])
                self.assertEqual(client.command({"type": "second"}), ["two"])

        create_connection.assert_called_once_with(
            "wss://ha.example.test/api/websocket", timeout=4
        )
        self.assertEqual(connection.sent[0], {"type": "auth", "access_token": TOKEN})
        self.assertEqual([message["id"] for message in connection.sent[1:]], [1, 2])
        self.assertTrue(connection.closed)

    def test_auth_invalid_raises_and_closes_connection(self):
        connection = FakeConnection(
            [{"type": "auth_required"}, {"type": "auth_invalid", "message": "bad token"}]
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with self.assertRaisesRegex(deploy_dashboards.DeploymentError, "authentication"):
                with deploy_dashboards.HomeAssistantWebSocket("https://ha.example.test", TOKEN):
                    pass
        self.assertTrue(connection.closed)

    def test_auth_failure_is_not_masked_by_close_failure(self):
        connection = FakeConnection(
            [{"type": "auth_required"}, {"type": "auth_invalid"}],
            close_error=RuntimeError(f"close leaked {TOKEN}"),
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                with deploy_dashboards.HomeAssistantWebSocket(
                    "https://ha.example.test", TOKEN
                ):
                    pass
        self.assertIn("authentication failed", str(raised.exception))
        self.assertNotIn("close", str(raised.exception))
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_command_failure_is_not_masked_by_close_failure(self):
        connection = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {
                    "id": 1,
                    "type": "result",
                    "success": False,
                    "error": {"code": "invalid_format", "message": "bad command"},
                },
            ],
            close_error=RuntimeError(f"close leaked {TOKEN}"),
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                with deploy_dashboards.HomeAssistantWebSocket(
                    "https://ha.example.test", TOKEN
                ) as client:
                    client.command({"type": "lovelace/config/save"})
        self.assertIn("lovelace/config/save", str(raised.exception))
        self.assertIn("invalid_format", str(raised.exception))
        self.assertNotIn("close leaked", str(raised.exception))
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_clean_exit_close_failure_is_safe(self):
        connection = FakeConnection(
            [{"type": "auth_required"}, {"type": "auth_ok"}],
            close_error=RuntimeError(f"close leaked {TOKEN}"),
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                with deploy_dashboards.HomeAssistantWebSocket(
                    "https://ha.example.test", TOKEN
                ):
                    pass
        self.assertEqual(
            str(raised.exception), "Failed to close Home Assistant WebSocket"
        )
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_failed_command_names_command_and_error_without_token(self):
        connection = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {
                    "id": 1,
                    "type": "result",
                    "success": False,
                    "error": {
                        "code": "invalid_format",
                        "message": f"bad request {TOKEN}",
                    },
                },
            ]
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with deploy_dashboards.HomeAssistantWebSocket(
                "https://ha.example.test", TOKEN
            ) as client:
                with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                    client.command({"type": "lovelace/config/save"})
        message = str(raised.exception)
        self.assertIn("lovelace/config/save", message)
        self.assertIn("invalid_format", message)
        self.assertNotIn(TOKEN, message)


class CliTests(unittest.TestCase):
    def test_main_returns_two_when_url_or_token_is_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(deploy_dashboards.main([]), 2)
        with mock.patch.dict(os.environ, {"HA_URL": "https://ha.example.test"}, clear=True), mock.patch(
            "sys.stderr", new=io.StringIO()
        ):
            self.assertEqual(deploy_dashboards.main([]), 2)
        with mock.patch.dict(os.environ, {"HA_TOKEN": TOKEN}, clear=True), mock.patch(
            "sys.stderr", new=io.StringIO()
        ):
            self.assertEqual(deploy_dashboards.main([]), 2)

    def test_main_reports_malformed_url_without_traceback(self):
        with mock.patch.dict(os.environ, {"HA_TOKEN": TOKEN}, clear=True), mock.patch(
            "sys.stderr", new=io.StringIO()
        ) as stderr:
            result = deploy_dashboards.main(
                ["--base-url", "http://[::1", "--manifest", str(MANIFEST)]
            )
        self.assertEqual(result, 1)
        self.assertIn("valid http or https URL", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertNotIn(TOKEN, stderr.getvalue())

    def test_main_dry_run_writes_preflight_without_network(self):
        client = FakeClient(deploy_dashboards.load_entries(ROOT, MANIFEST))
        real_preflight = deploy_dashboards.preflight
        context_manager = mock.MagicMock()
        context_manager.__enter__.return_value = client
        context_manager.__exit__.return_value = False
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"HA_URL": "https://ha.example.test", "HA_TOKEN": TOKEN},
            clear=True,
        ), mock.patch.object(
            deploy_dashboards, "HomeAssistantWebSocket", return_value=context_manager
        ), mock.patch.object(
            deploy_dashboards,
            "preflight",
            side_effect=lambda fake_client, base_url, token, entries: real_preflight(
                fake_client, base_url, token, entries, lambda *_: True
            ),
        ), mock.patch(
            "sys.stdout", new=io.StringIO()
        ) as stdout:
            result = deploy_dashboards.main(
                ["--manifest", str(MANIFEST), "--artifact-dir", temp_dir]
            )
            preflight = json.loads(
                (Path(temp_dir) / "preflight.json").read_text(encoding="utf-8")
            )
        self.assertEqual(result, 0)
        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "dry-run")


if __name__ == "__main__":
    unittest.main()
