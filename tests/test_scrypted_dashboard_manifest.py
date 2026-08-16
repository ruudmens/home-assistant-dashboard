"""Contract tests for the isolated Scrypted camera dashboard manifest."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
CAMERA_MANIFEST = ROOT / "tools" / "scrypted_dashboard_manifest.yaml"
ORIGINAL_MANIFEST = ROOT / "tools" / "dashboard_manifest.yaml"

EXPECTED_REQUIREMENTS = [
    {
        "type": "module",
        "url_suffix": "/hacsfiles/lovelace-layout-card/layout-card.js",
    },
    {
        "type": "module",
        "url_suffix": "/hacsfiles/button-card/button-card.js",
    },
    {
        "type": "module",
        "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.js",
    },
    {
        "type": "css",
        "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.css",
    },
]


def load_manifest_document(path: Path) -> dict:
    """Load manifest metadata without following dashboard config paths."""
    with path.open(encoding="utf-8") as manifest_file:
        document = yaml.safe_load(manifest_file)
    return {
        "entries": document["dashboards"],
        "resource_requirements": document.get("resource_requirements", []),
    }


class ScryptedDashboardManifestTests(unittest.TestCase):
    def test_camera_manifest_contains_only_the_camera_dashboard(self):
        manifest = load_manifest_document(CAMERA_MANIFEST)

        self.assertEqual(
            [entry["url_path"] for entry in manifest["entries"]],
            ["luxury-cameras"],
        )
        self.assertEqual(manifest["entries"][0]["title"], "Luxury Cameras")
        self.assertEqual(manifest["entries"][0]["icon"], "mdi:cctv")
        self.assertEqual(manifest["entries"][0]["mode"], "storage")
        self.assertIs(manifest["entries"][0]["show_in_sidebar"], True)
        self.assertIs(manifest["entries"][0]["require_admin"], False)
        self.assertEqual(
            manifest["entries"][0]["config"],
            "dashboards/luxury_cameras.yaml",
        )

    def test_camera_manifest_requires_exact_sanitized_frontend_resources(self):
        manifest = load_manifest_document(CAMERA_MANIFEST)

        self.assertEqual(manifest["resource_requirements"], EXPECTED_REQUIREMENTS)

    def test_original_manifest_remains_isolated_from_camera_dashboard(self):
        original_text = ORIGINAL_MANIFEST.read_text(encoding="utf-8")
        original = yaml.safe_load(original_text)

        self.assertEqual(
            [entry["url_path"] for entry in original["dashboards"]],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )
        self.assertNotIn("luxury-cameras", original_text)


if __name__ == "__main__":
    unittest.main()
