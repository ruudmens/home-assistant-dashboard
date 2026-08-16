"""Tests for the Home Assistant dashboard deployment client."""

import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib import error as urllib_error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        panels=None,
        fail_create_after_append=None,
        unexpected_save=None,
        config_mismatch=None,
        missing_created_on_final=None,
        changed_created_on_final=None,
        fail_reconcile=False,
        wrong_created_path=None,
        third_party_remote_on_create_failure=False,
        mismatched_ambiguous_create=False,
        definitive_rejection_with_third_party=None,
        malformed_create_success=None,
        ambiguous_create_missing_registry=False,
        resources=None,
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
        self.panels = panels or {}
        self.fail_create_after_append = fail_create_after_append
        self.unexpected_save = unexpected_save
        self.config_mismatch = config_mismatch
        self.missing_created_on_final = missing_created_on_final
        self.changed_created_on_final = changed_created_on_final
        self.fail_reconcile = fail_reconcile
        self.wrong_created_path = wrong_created_path
        self.third_party_remote_on_create_failure = third_party_remote_on_create_failure
        self.mismatched_ambiguous_create = mismatched_ambiguous_create
        self.definitive_rejection_with_third_party = definitive_rejection_with_third_party
        self.malformed_create_success = malformed_create_success
        self.ambiguous_create_missing_registry = ambiguous_create_missing_registry
        self.resources = [] if resources is None else resources
        self.commands = []
        self.configs = {}
        self.deleted = []
        self.list_calls = 0
        self.create_failed = False
        self.warnings = []

    def command(self, payload):
        self.commands.append(dict(payload))
        command_type = payload["type"]
        if command_type == "lovelace/dashboards/list":
            self.list_calls += 1
            if self.fail_reconcile and self.create_failed:
                raise deploy_dashboards.DeploymentError("dashboard reconciliation unavailable")
            dashboards = [dict(dashboard) for dashboard in self.dashboards]
            if self.list_calls == 2 and self.missing_created_on_final:
                dashboards = [
                    dashboard
                    for dashboard in dashboards
                    if dashboard.get("url_path") != self.missing_created_on_final
                ]
            if self.list_calls == 2 and self.changed_created_on_final:
                for dashboard in dashboards:
                    if dashboard.get("url_path") == self.changed_created_on_final:
                        dashboard["title"] = "Changed behind our back"
            return dashboards
        if command_type == "get_panels":
            return {key: dict(value) for key, value in self.panels.items()}
        if command_type == "get_states":
            return list(self.states)
        if command_type == "lovelace/resources":
            return [dict(resource) for resource in self.resources]
        if command_type == "lovelace/dashboards/create":
            dashboard = dict(payload)
            dashboard.pop("type")
            dashboard["id"] = f'{payload["url_path"]}-id'
            if payload["url_path"] == self.definitive_rejection_with_third_party:
                third_party = dict(dashboard)
                third_party["id"] = f'third-party-{payload["url_path"]}-id'
                self.dashboards.append(third_party)
                raise deploy_dashboards.CommandRejectedError(
                    "url_already_exists: dashboard route already exists"
                )
            if payload["url_path"] == self.wrong_created_path:
                dashboard["url_path"] = "wrong-returned-path"
            if (
                payload["url_path"] == self.fail_create_after_append
                and self.mismatched_ambiguous_create
            ):
                dashboard["title"] = "Concurrent dashboard"
            self.dashboards.append(dashboard)
            if payload["url_path"] == self.fail_create_after_append:
                if self.ambiguous_create_missing_registry:
                    self.dashboards = [
                        current
                        for current in self.dashboards
                        if current.get("id") != dashboard["id"]
                    ]
                if self.third_party_remote_on_create_failure:
                    remote_entry = next(
                        entry for entry in self.entries if entry["url_path"] == "luxury-remote"
                    )
                    self.dashboards.append(
                        {
                            "id": "third-party-remote-id",
                            "url_path": remote_entry["url_path"],
                            "title": remote_entry["title"],
                            "icon": remote_entry["icon"],
                            "mode": remote_entry["mode"],
                            "show_in_sidebar": remote_entry["show_in_sidebar"],
                            "require_admin": remote_entry["require_admin"],
                        }
                    )
                self.create_failed = True
                raise deploy_dashboards.AmbiguousCommandError(
                    f'create response lost for {payload["url_path"]}'
                )
            if payload["url_path"] == self.malformed_create_success:
                malformed_response = dict(dashboard)
                malformed_response.pop("id")
                return malformed_response
            return dict(dashboard)
        if command_type == "lovelace/config/save":
            if payload["url_path"] == self.unexpected_save:
                raise RuntimeError(f"unexpected save failure with {TOKEN}")
            if payload["url_path"] == self.fail_save:
                raise deploy_dashboards.DeploymentError(
                    f"save failed for {payload['url_path']}: invalid_format: safe reason"
                )
            self.configs[payload["url_path"]] = payload["config"]
            return None
        if command_type == "lovelace/config":
            if payload["url_path"] == self.config_mismatch:
                return {"changed": True}
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

    def test_load_manifest_returns_validated_resource_requirements(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dashboards").mkdir()
            (root / "dashboards" / "test.yaml").write_text(
                "title: Luxury Test\n", encoding="utf-8"
            )
            manifest_path = root / "manifest.yaml"
            manifest_path.write_text(
                """resource_requirements:
  - type: module
    url_suffix: /endpoint/@scrypted/nvr/assets/web-components.js
  - type: css
    url_suffix: /endpoint/@scrypted/nvr/assets/web-components.css
dashboards:
  - url_path: luxury-test
    title: Luxury Test
    icon: mdi:cctv
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/test.yaml
""",
                encoding="utf-8",
            )

            manifest = deploy_dashboards.load_manifest(root, manifest_path)

            self.assertEqual(
                manifest["resource_requirements"],
                [
                    {
                        "type": "module",
                        "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.js",
                    },
                    {
                        "type": "css",
                        "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.css",
                    },
                ],
            )
            self.assertEqual(
                [entry["url_path"] for entry in manifest["entries"]], ["luxury-test"]
            )

        original_manifest = deploy_dashboards.load_manifest(ROOT, MANIFEST)
        self.assertEqual(original_manifest["resource_requirements"], [])
        self.assertEqual(
            [entry["url_path"] for entry in deploy_dashboards.load_entries(ROOT, MANIFEST)],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )

    def test_load_manifest_rejects_unsafe_resource_requirements(self):
        invalid_requirements = [
            "not-a-list",
            ["not-a-mapping"],
            [{"type": "javascript", "url_suffix": "/safe.js"}],
            [{"type": "module", "url_suffix": "relative.js"}],
            [{"type": "module", "url_suffix": "https://evil.example/x.js"}],
            [{"type": "module", "url_suffix": "//evil.example/x.js"}],
            [{"type": "module", "url_suffix": "/x.js?token=secret"}],
            [{"type": "module", "url_suffix": "/x.js#fragment"}],
            [
                {"type": "module", "url_suffix": "/safe.js"},
                {"type": "module", "url_suffix": "/safe.js"},
            ],
        ]
        dashboard = {
            "url_path": "luxury-test",
            "title": "Luxury Test",
            "icon": "mdi:cctv",
            "mode": "storage",
            "show_in_sidebar": True,
            "require_admin": False,
            "config": "dashboards/test.yaml",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dashboards").mkdir()
            (root / "dashboards" / "test.yaml").write_text(
                "title: Luxury Test\n", encoding="utf-8"
            )
            manifest_path = root / "manifest.yaml"
            for requirements in invalid_requirements:
                with self.subTest(requirements=requirements):
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "resource_requirements": requirements,
                                "dashboards": [dashboard],
                            }
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        deploy_dashboards.DeploymentError,
                        "^Unable to load dashboard manifest or config YAML$",
                    ) as raised:
                        deploy_dashboards.load_manifest(root, manifest_path)
                    self.assertNotIn(TOKEN, str(raised.exception))
                    self.assertIsNone(raised.exception.__cause__)

    def test_load_entries_rejects_config_path_outside_root_without_leaking_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "root"
            root.mkdir()
            outside = parent / "outside.yaml"
            outside.write_text(f"secret: {TOKEN}\n", encoding="utf-8")
            manifest = root / "manifest.yaml"
            manifest.write_text(
                json.dumps(
                    {
                        "dashboards": [
                            {
                                "url_path": "safe",
                                "title": "Safe",
                                "icon": "mdi:home",
                                "mode": "storage",
                                "show_in_sidebar": True,
                                "require_admin": False,
                                "config": "../outside.yaml",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                deploy_dashboards.load_entries(root, manifest)
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_load_entries_rejects_malformed_manifest_shapes_and_types(self):
        valid_entry = {
            "url_path": "safe",
            "title": "Safe",
            "icon": "mdi:home",
            "mode": "storage",
            "show_in_sidebar": True,
            "require_admin": False,
            "config": "dashboard.yaml",
        }
        malformed = [
            [],
            {"dashboards": {}},
            {"dashboards": [dict(valid_entry, url_path=7)]},
            {"dashboards": [dict(valid_entry, show_in_sidebar="true")]},
            {"dashboards": [dict(valid_entry, mode="yaml")]},
            {"dashboards": [{key: value for key, value in valid_entry.items() if key != "icon"}]},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dashboard.yaml").write_text("title: Safe\n", encoding="utf-8")
            manifest = root / "manifest.yaml"
            for value in malformed:
                with self.subTest(value=value):
                    manifest.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                        deploy_dashboards.load_entries(root, manifest)
                    self.assertNotIn(TOKEN, str(raised.exception))

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

    def test_preflight_rejects_duplicate_manifest_paths_before_any_command(self):
        entries = [dict(entry) for entry in self.entries]
        entries[2]["url_path"] = entries[1]["url_path"]
        client = FakeClient(entries)
        with self.assertRaisesRegex(
            deploy_dashboards.DeploymentError, "(?i)duplicate.*luxury-garage"
        ):
            deploy_dashboards.preflight(
                client, "https://ha.example.test", TOKEN, entries, lambda *_: True
            )
        self.assertEqual(client.commands, [])

    def test_preflight_rejects_second_and_third_target_panel_routes(self):
        panel_cases = [
            {"garage-route": {"url_path": "luxury-garage"}},
            {"luxury-remote": {"title": "Remote panel"}},
        ]
        for panels in panel_cases:
            with self.subTest(panels=panels):
                client = FakeClient(self.entries, panels=panels)
                with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                    deploy_dashboards.preflight(
                        client,
                        "https://ha.example.test",
                        TOKEN,
                        self.entries,
                        lambda *_: True,
                    )
                self.assertTrue(
                    any(path in str(raised.exception) for path in ("luxury-garage", "luxury-remote"))
                )
                self.assertEqual(
                    [command["type"] for command in client.commands],
                    ["lovelace/dashboards/list", "get_panels"],
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

    def test_preflight_verifies_dynamic_resources_without_persisting_runtime_url(self):
        runtime_token = "runtime-query-secret"
        runtime_url = (
            "/endpoint/@scrypted/nvr/assets/web-components.js"
            f"?token={runtime_token}"
        )
        requirement = {
            "type": "module",
            "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.js",
        }
        client = FakeClient(
            self.entries,
            resources=[{"type": "module", "url": runtime_url}],
        )
        checked = []

        def checker(base_url, token, path):
            checked.append((base_url, token, path))
            return True

        report = deploy_dashboards.preflight(
            client,
            "https://ha.example.test",
            TOKEN,
            self.entries,
            resource_checker=checker,
            resource_requirements=[requirement],
        )

        self.assertEqual(checked[-1], ("https://ha.example.test", TOKEN, runtime_url))
        self.assertEqual(report["verified_resource_requirements"], [requirement])
        self.assertNotIn(runtime_token, json.dumps(report))
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "preflight.json"
            deploy_dashboards.write_json(artifact, report)
            self.assertNotIn(runtime_token, artifact.read_text(encoding="utf-8"))
        self.assertIn({"type": "lovelace/resources"}, client.commands)

    def test_preflight_rejects_missing_duplicate_and_wrong_type_dynamic_resources(self):
        suffix = "/endpoint/@scrypted/nvr/assets/web-components.js"
        requirement = {"type": "module", "url_suffix": suffix}
        cases = [
            [],
            [
                {"type": "module", "url": suffix + "?token=first-secret"},
                {"type": "module", "url": suffix + "?token=second-secret"},
            ],
            [{"type": "css", "url": suffix + "?token=wrong-type-secret"}],
        ]
        for resources in cases:
            with self.subTest(resources=resources):
                client = FakeClient(self.entries, resources=resources)
                with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                    deploy_dashboards.preflight(
                        client,
                        "https://ha.example.test",
                        TOKEN,
                        self.entries,
                        resource_checker=lambda *_: True,
                        resource_requirements=[requirement],
                    )
                message = str(raised.exception)
                self.assertIn(suffix, message)
                self.assertNotIn("first-secret", message)
                self.assertNotIn("second-secret", message)
                self.assertNotIn("wrong-type-secret", message)

    def test_preflight_rejects_unsafe_registered_resource_urls(self):
        suffix = "/endpoint/@scrypted/nvr/assets/web-components.js"
        requirement = {"type": "module", "url_suffix": suffix}
        unsafe_urls = [
            "https://evil.example" + suffix,
            "//evil.example" + suffix,
            "https://user:password@evil.example" + suffix,
            suffix + "#fragment",
        ]
        for registered_url in unsafe_urls:
            with self.subTest(registered_url=registered_url):
                client = FakeClient(
                    self.entries,
                    resources=[{"type": "module", "url": registered_url}],
                )
                checker = mock.Mock(return_value=True)
                with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                    deploy_dashboards.preflight(
                        client,
                        "https://ha.example.test",
                        TOKEN,
                        self.entries,
                        resource_checker=checker,
                        resource_requirements=[requirement],
                    )
                self.assertIn(suffix, str(raised.exception))
                self.assertNotIn(registered_url, str(raised.exception))
                self.assertEqual(
                    [call.args[2] for call in checker.call_args_list],
                    list(deploy_dashboards.REQUIRED_RESOURCES),
                )

    def test_preflight_ignores_unsafe_same_type_resources_with_unrelated_paths(self):
        suffix = "/endpoint/@scrypted/nvr/assets/web-components.js"
        runtime_url = suffix + "?token=runtime-query-secret"
        requirement = {"type": "module", "url_suffix": suffix}
        client = FakeClient(
            self.entries,
            resources=[
                {"type": "module", "url": "https://evil.example/unrelated.js"},
                {"type": "module", "url": "/unrelated.css#fragment"},
                {"type": "module", "url": runtime_url},
            ],
        )
        checker = mock.Mock(return_value=True)

        report = deploy_dashboards.preflight(
            client,
            "https://ha.example.test",
            TOKEN,
            self.entries,
            resource_checker=checker,
            resource_requirements=[requirement],
        )

        self.assertEqual(report["verified_resource_requirements"], [requirement])
        self.assertEqual(checker.call_args_list[-1].args[2], runtime_url)

    def test_dynamic_resource_checker_failure_does_not_expose_runtime_query(self):
        runtime_token = "runtime-error-secret"
        suffix = "/endpoint/@scrypted/nvr/assets/web-components.css"
        client = FakeClient(
            self.entries,
            resources=[{"type": "css", "url": suffix + f"?token={runtime_token}"}],
        )
        requirement = {"type": "css", "url_suffix": suffix}

        def checker(_base_url, _token, runtime_url):
            if runtime_token in runtime_url:
                raise deploy_dashboards.DeploymentError(
                    f"network failure for {runtime_url}"
                )
            return True

        with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
            deploy_dashboards.preflight(
                client,
                "https://ha.example.test",
                TOKEN,
                self.entries,
                resource_checker=checker,
                resource_requirements=[requirement],
            )
        self.assertIn(suffix, str(raised.exception))
        self.assertNotIn(runtime_token, str(raised.exception))

    def test_preflight_without_dynamic_requirements_keeps_fixed_resource_checks(self):
        client = FakeClient(self.entries)
        checked = []
        report = deploy_dashboards.preflight(
            client,
            "https://ha.example.test",
            TOKEN,
            self.entries,
            lambda _base_url, _token, path: checked.append(path) or True,
        )
        self.assertEqual(checked, list(deploy_dashboards.REQUIRED_RESOURCES))
        self.assertEqual(
            report["verified_resources"], list(deploy_dashboards.REQUIRED_RESOURCES)
        )
        self.assertEqual(report["verified_resource_requirements"], [])
        self.assertNotIn(
            "lovelace/resources", [command["type"] for command in client.commands]
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
            self.assertIn("invalid_format: safe reason", failure["error"])
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

    def test_create_response_loss_reconciles_and_deletes_server_side_dashboard(self):
        client = FakeClient(self.entries, fail_create_after_append="luxury-garage")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError, "create response lost for luxury-garage"
            ):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(client.deleted, ["luxury-garage-id", "luxury-home-id"])
        self.assertEqual(client.dashboards, [client.original])
        self.assertEqual(failure["status"], "rolled_back")

    def test_definitive_create_rejection_never_deletes_identical_third_party(self):
        client = FakeClient(
            self.entries,
            definitive_rejection_with_third_party="luxury-home",
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError, "url_already_exists"
            ):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(client.deleted, [])
        self.assertEqual(
            [dashboard["id"] for dashboard in client.dashboards],
            ["overview", "third-party-luxury-home-id"],
        )
        self.assertEqual(client.list_calls, 1)
        self.assertEqual(failure["status"], "rolled_back")

    def test_malformed_successful_create_is_reconciled_as_ambiguous(self):
        client = FakeClient(self.entries, malformed_create_success="luxury-home")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError, "no dashboard ID"
            ):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
        self.assertEqual(client.deleted, ["luxury-home-id"])
        self.assertEqual(client.dashboards, [client.original])

    def test_reconciliation_ignores_third_party_on_unattempted_remote_path(self):
        client = FakeClient(
            self.entries,
            fail_create_after_append="luxury-home",
            third_party_remote_on_create_failure=True,
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(client.deleted, ["luxury-home-id"])
        self.assertEqual(
            [dashboard["id"] for dashboard in client.dashboards],
            ["overview", "third-party-remote-id"],
        )
        self.assertEqual(failure["status"], "rolled_back")

    def test_reconciliation_preserves_mismatched_attempted_path_for_manual_review(self):
        client = FakeClient(
            self.entries,
            fail_create_after_append="luxury-home",
            mismatched_ambiguous_create=True,
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(client.deleted, [])
        self.assertEqual(
            [dashboard["id"] for dashboard in client.dashboards],
            ["overview", "luxury-home-id"],
        )
        self.assertEqual(failure["status"], "rollback_incomplete")
        self.assertTrue(
            any("manual reconciliation" in message.lower() for message in failure["rollback_errors"])
        )

    def test_ambiguous_create_without_registry_match_requires_manual_reconciliation(self):
        client = FakeClient(
            self.entries,
            fail_create_after_append="luxury-home",
            ambiguous_create_missing_registry=True,
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure_text = (Path(temp_dir) / "deployment-failure.json").read_text(
                encoding="utf-8"
            )
            failure = json.loads(failure_text)
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.dashboards, [client.original])
        self.assertEqual(failure["status"], "rollback_incomplete")
        self.assertTrue(
            any("manual reconciliation" in message.lower() for message in failure["rollback_errors"])
        )
        self.assertNotIn(TOKEN, failure_text)

    def test_failed_rollback_reconciliation_is_recorded_incomplete(self):
        client = FakeClient(
            self.entries,
            fail_create_after_append="luxury-home",
            fail_reconcile=True,
        )
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertEqual(failure["status"], "rollback_incomplete")
        self.assertTrue(
            any("reconcile" in message for message in failure["rollback_errors"])
        )
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.dashboards[0], client.original)

    def test_unexpected_failure_detail_is_not_copied_to_error_or_artifact(self):
        client = FakeClient(self.entries, unexpected_save="luxury-home")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(deploy_dashboards.DeploymentError) as raised:
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure_text = (Path(temp_dir) / "deployment-failure.json").read_text(
                encoding="utf-8"
            )
        self.assertIn("unexpected internal error", str(raised.exception).lower())
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertNotIn(TOKEN, failure_text)

    def test_saved_config_mismatch_detail_is_preserved_safely(self):
        client = FakeClient(self.entries, config_mismatch="luxury-home")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError,
                "Saved dashboard config differs for luxury-home",
            ):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
            failure = json.loads(
                (Path(temp_dir) / "deployment-failure.json").read_text(encoding="utf-8")
            )
        self.assertIn("Saved dashboard config differs for luxury-home", failure["error"])
        self.assertEqual(client.deleted, ["luxury-home-id"])

    def test_missing_or_changed_created_final_record_triggers_full_rollback(self):
        cases = [
            {"missing_created_on_final": "luxury-garage"},
            {"changed_created_on_final": "luxury-remote"},
        ]
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp_dir:
                client = FakeClient(self.entries, **options)
                report = deploy_dashboards.preflight(
                    client,
                    "https://ha.example.test",
                    TOKEN,
                    self.entries,
                    lambda *_: True,
                )
                with self.assertRaisesRegex(
                    deploy_dashboards.DeploymentError, "Created dashboard"
                ):
                    deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
                self.assertEqual(
                    client.deleted,
                    ["luxury-remote-id", "luxury-garage-id", "luxury-home-id"],
                )
                self.assertEqual(client.dashboards, [client.original])

    def test_wrong_created_response_path_is_rejected_and_rolled_back_by_id(self):
        client = FakeClient(self.entries, wrong_created_path="luxury-home")
        report = deploy_dashboards.preflight(
            client, "https://ha.example.test", TOKEN, self.entries, lambda *_: True
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                deploy_dashboards.DeploymentError,
                "Created dashboard metadata differs for luxury-home",
            ):
                deploy_dashboards.deploy(client, self.entries, report, Path(temp_dir))
        self.assertEqual(client.deleted, ["luxury-home-id"])
        self.assertEqual(client.dashboards, [client.original])


class HttpResourceTests(unittest.TestCase):
    def test_http_resource_status_rejects_three_hundred_responses(self):
        response = urllib_error.HTTPError(
            "https://ha.example.test/resource.js", 304, "Not Modified", {}, None
        )
        opener = mock.MagicMock()
        opener.open.side_effect = response
        with mock.patch.object(
            deploy_dashboards.urllib_request, "build_opener", return_value=opener
        ):
            self.assertFalse(
                deploy_dashboards.http_resource_status(
                    "https://ha.example.test", TOKEN, "/resource.js"
                )
            )

    def test_http_resource_redirect_never_forwards_authorization(self):
        initial_authorization = []
        target_authorization = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                target_authorization.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, _format, *args):
                pass

        target_server = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = threading.Thread(target=target_server.serve_forever, daemon=True)
        target_thread.start()
        target_url = f"http://127.0.0.1:{target_server.server_port}/target"

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                initial_authorization.append(self.headers.get("Authorization"))
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()

            def log_message(self, _format, *args):
                pass

        redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        redirect_thread = threading.Thread(target=redirect_server.serve_forever, daemon=True)
        redirect_thread.start()
        try:
            available = deploy_dashboards.http_resource_status(
                f"http://127.0.0.1:{redirect_server.server_port}",
                TOKEN,
                "/resource.js",
            )
        finally:
            redirect_server.shutdown()
            redirect_server.server_close()
            redirect_thread.join(timeout=2)
            target_server.shutdown()
            target_server.server_close()
            target_thread.join(timeout=2)

        self.assertFalse(available)
        self.assertEqual(initial_authorization, [f"Bearer {TOKEN}"])
        self.assertEqual(target_authorization, [])

    def test_http_resource_status_rejects_http_error(self):
        response = urllib_error.HTTPError(
            "https://ha.example.test/resource.js", 404, "Not Found", {}, None
        )
        opener = mock.MagicMock()
        opener.open.side_effect = response
        with mock.patch.object(
            deploy_dashboards.urllib_request, "build_opener", return_value=opener
        ):
            self.assertFalse(
                deploy_dashboards.http_resource_status(
                    "https://ha.example.test", TOKEN, "/resource.js"
                )
            )

    def test_http_resource_network_error_does_not_expose_token(self):
        opener = mock.MagicMock()
        opener.open.side_effect = urllib_error.URLError(f"network rejected {TOKEN}")
        with mock.patch.object(
            deploy_dashboards.urllib_request,
            "build_opener",
            return_value=opener,
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
            with deploy_dashboards.HomeAssistantWebSocket(
                "https://ha.example.test", TOKEN
            ) as client:
                pass
        self.assertEqual(client.warnings, ["Failed to close Home Assistant WebSocket"])
        self.assertNotIn(TOKEN, json.dumps(client.warnings))

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
                with self.assertRaises(deploy_dashboards.CommandRejectedError) as raised:
                    client.command({"type": "lovelace/config/save"})
        message = str(raised.exception)
        self.assertIn("lovelace/config/save", message)
        self.assertIn("invalid_format", message)
        self.assertNotIn(TOKEN, message)

    def test_receive_loss_after_command_send_is_ambiguous_and_safe(self):
        connection = FakeConnection(
            [{"type": "auth_required"}, {"type": "auth_ok"}]
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with deploy_dashboards.HomeAssistantWebSocket(
                "https://ha.example.test", TOKEN
            ) as client:
                with self.assertRaises(deploy_dashboards.AmbiguousCommandError) as raised:
                    client.command({"type": "lovelace/dashboards/create"})
        self.assertIn("outcome is unknown", str(raised.exception))
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_correlated_result_missing_success_is_ambiguous(self):
        connection = FakeConnection(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"id": 1, "type": "result", "result": {}},
            ]
        )
        with mock.patch.object(
            deploy_dashboards.websocket, "create_connection", return_value=connection
        ):
            with deploy_dashboards.HomeAssistantWebSocket(
                "https://ha.example.test", TOKEN
            ) as client:
                with self.assertRaises(deploy_dashboards.AmbiguousCommandError):
                    client.command({"type": "lovelace/dashboards/create"})


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
            side_effect=lambda fake_client, base_url, token, entries,
            resource_requirements=(): real_preflight(
                fake_client,
                base_url,
                token,
                entries,
                lambda *_: True,
                resource_requirements=resource_requirements,
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
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["status"], "dry-run")
        self.assertEqual(output["warnings"], [])

    def test_main_apply_success_survives_close_error_and_prints_safe_warning(self):
        client = FakeClient(deploy_dashboards.load_entries(ROOT, MANIFEST))
        real_preflight = deploy_dashboards.preflight

        class CloseWarningContext:
            def __enter__(self):
                return client

            def __exit__(self, _exc_type, _exc_value, _traceback):
                client.warnings.append("Failed to close Home Assistant WebSocket")
                return False

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"HA_URL": "https://ha.example.test", "HA_TOKEN": TOKEN},
            clear=True,
        ), mock.patch.object(
            deploy_dashboards, "HomeAssistantWebSocket", return_value=CloseWarningContext()
        ), mock.patch.object(
            deploy_dashboards,
            "preflight",
            side_effect=lambda fake_client, base_url, token, entries,
            resource_requirements=(): real_preflight(
                fake_client,
                base_url,
                token,
                entries,
                lambda *_: True,
                resource_requirements=resource_requirements,
            ),
        ), mock.patch(
            "sys.stdout", new=io.StringIO()
        ) as stdout, mock.patch(
            "sys.stderr", new=io.StringIO()
        ) as stderr:
            return_code = deploy_dashboards.main(
                [
                    "--manifest",
                    str(MANIFEST),
                    "--artifact-dir",
                    temp_dir,
                    "--apply",
                ]
            )
        output = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 0)
        self.assertEqual(output["status"], "deployed")
        self.assertEqual(output["warnings"], ["Failed to close Home Assistant WebSocket"])
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(TOKEN, json.dumps(output))


if __name__ == "__main__":
    unittest.main()
