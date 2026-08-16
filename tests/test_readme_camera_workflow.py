"""Documentation contract for the isolated Luxury Cameras workflow."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class ReadmeCameraWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_responsive_dashboard_table_includes_camera_url(self):
        self.assertIn(
            "| Luxury Cameras | `/luxury-cameras/cameras` |",
            self.readme,
        )

    def test_camera_workflow_documents_prerequisites_and_performance_choice(self):
        self.assertIn(
            "[official Scrypted Home Assistant documentation]"
            "(https://docs.scrypted.app/home-assistant.html)",
            self.readme,
        )
        self.assertIn("Scrypted integration", self.readme)
        self.assertIn("NVR frontend resources", self.readme)
        self.assertIn("low-resolution autoplay", self.readme)
        self.assertIn("Home Assistant responsive", self.readme)

    def test_camera_workflow_has_exact_isolated_dry_run_and_apply_commands(self):
        self.assertIn(
            "python tools/deploy_dashboards.py "
            "--manifest tools/scrypted_dashboard_manifest.yaml\n",
            self.readme,
        )
        self.assertIn(
            "python tools/deploy_dashboards.py "
            "--manifest tools/scrypted_dashboard_manifest.yaml --apply",
            self.readme,
        )
        self.assertIn("adds only `luxury-cameras`", self.readme)

    def test_camera_workflow_preserves_credential_and_artifact_safety(self):
        self.assertIn("process-scoped `HA_TOKEN`", self.readme)
        self.assertIn("same secure prompt", self.readme)
        self.assertIn("resolved only in memory", self.readme)
        self.assertIn("only sanitized suffixes", self.readme)

    def test_camera_cleanup_is_separate_from_original_three_dashboard_scope(self):
        original_cleanup = (
            "delete only dashboard records whose URL paths are exactly "
            "`luxury-home`, `luxury-garage`, and `luxury-remote`"
        )
        self.assertIn(original_cleanup, self.readme)
        self.assertNotIn(
            "`luxury-home`, `luxury-garage`, `luxury-remote`, and "
            "`luxury-cameras`",
            self.readme,
        )
        self.assertIn(
            "delete only the dashboard record whose URL path is exactly "
            "`luxury-cameras`",
            self.readme,
        )


if __name__ == "__main__":
    unittest.main()
