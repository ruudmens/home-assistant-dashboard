"""Tests for the luxury dashboard manifest contract."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "dashboard_manifest.yaml"


class DashboardManifestTests(unittest.TestCase):
    def test_luxury_dashboard_manifest_contract(self):
        with MANIFEST.open(encoding="utf-8") as manifest_file:
            dashboards = yaml.safe_load(manifest_file)["dashboards"]

        self.assertEqual(
            [dashboard["url_path"] for dashboard in dashboards],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )
        self.assertEqual(
            [dashboard["title"] for dashboard in dashboards],
            ["Luxury Home", "Luxury Garage", "Luxury Remote"],
        )
        self.assertTrue(all(dashboard["mode"] == "storage" for dashboard in dashboards))
        self.assertTrue(all(dashboard["show_in_sidebar"] is True for dashboard in dashboards))
        self.assertTrue(all(dashboard["require_admin"] is False for dashboard in dashboards))
        self.assertEqual(
            [dashboard["config"] for dashboard in dashboards],
            [
                "dashboards/luxury_home.yaml",
                "dashboards/luxury_garage.yaml",
                "dashboards/luxury_remote.yaml",
            ],
        )


if __name__ == "__main__":
    unittest.main()
