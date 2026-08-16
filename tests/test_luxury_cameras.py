"""Contract tests for the responsive Luxury Cameras dashboard."""

from collections import Counter
from pathlib import Path
import re
import unittest
from urllib import parse as urllib_parse

from tests.config_assertions import load_config, walk


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = "dashboards/luxury_cameras.yaml"
EXPECTED_CAMERA_IDS = {
    107,
    124,
    171,
    173,
    250,
    264,
    266,
    267,
    268,
    269,
    270,
    271,
    286,
    287,
    288,
    289,
    290,
}
EXPECTED_CAMERA_ORDER = [
    107,
    266,
    124,
    268,
    267,
    287,
    286,
    289,
    288,
    290,
    269,
    250,
    264,
    171,
    173,
    270,
    271,
]
EXPECTED_DISPLAY_LABELS = [
    "Front Door",
    "Back Yard",
    "Bedroom",
    "Living Room",
    "Back Yard 2",
    "Blink Backyard",
    "Blink Backyard 2",
    "GNT2 Camera",
    "Living Room 2",
    "Mini Camera",
    "OG Camera",
    "RTSP Camera A",
    "RTSP Camera B",
    "Tapo C211 A",
    "Tapo C211 B",
    "U1",
    "V4",
]
EXPECTED_LIVE_IDS = [107, 266, 124, 268]
EXPECTED_NAVIGATION_PATHS = [
    "/luxury-home/home",
    "/luxury-garage/garage",
    "/luxury-remote/remote",
]
RFC1918 = re.compile(
    r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
)
URL = re.compile(r"\b(?:https?|rtsps?)://[^\s\"'<>]+", re.IGNORECASE)
CREDENTIAL_MARKERS = ("access_token", "bearer", "ha_token", "token=")


def scalar_strings(value):
    """Yield every string scalar from a nested Lovelace configuration."""
    if isinstance(value, dict):
        for child in value.values():
            yield from scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_strings(child)
    elif isinstance(value, str):
        yield value


class LuxuryCamerasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / CONFIG_PATH
        cls.text = cls.path.read_text(encoding="utf-8")
        cls.config = load_config(ROOT, CONFIG_PATH)
        cls.nodes = [node for node in walk(cls.config) if isinstance(node, dict)]
        cls.camera_cards = [
            node
            for node in cls.nodes
            if node.get("type") == "custom:scrypted-nvr-camera"
        ]

    def test_has_one_four_column_sections_camera_view(self):
        views = self.config["views"]

        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].get("path"), "cameras")
        self.assertEqual(views[0].get("type"), "sections")
        self.assertEqual(views[0].get("max_columns"), 4)

    def test_contains_exact_section_labels(self):
        labels = {self.config.get("title")}
        labels.update(
            node["heading"] for node in self.nodes if isinstance(node.get("heading"), str)
        )

        self.assertTrue(
            {"Luxury Cameras", "LIVE NOW", "ALL CAMERAS", "EVENT REEL"}.issubset(labels)
        )

    def test_camera_ids_are_exact_and_unique(self):
        id_counts = Counter(card.get("id") for card in self.camera_cards)

        self.assertEqual(set(id_counts), EXPECTED_CAMERA_IDS)
        self.assertEqual(id_counts, Counter({camera_id: 1 for camera_id in EXPECTED_CAMERA_IDS}))
        self.assertEqual([card["id"] for card in self.camera_cards], EXPECTED_CAMERA_ORDER)

    def test_all_camera_display_labels_are_exact(self):
        scalars = set(scalar_strings(self.config))

        for label in EXPECTED_DISPLAY_LABELS:
            self.assertIn(label, scalars)

    def test_only_primary_camera_ids_autoplay_in_design_order(self):
        self.assertEqual(
            [card["id"] for card in self.camera_cards if card.get("live") is True],
            EXPECTED_LIVE_IDS,
        )
        for card in self.camera_cards:
            if card["id"] not in EXPECTED_LIVE_IDS:
                self.assertNotIn("live", card)

    def test_every_camera_card_uses_the_safe_low_resolution_contract(self):
        expected = {
            "type": "custom:scrypted-nvr-camera",
            "destination": "low-resolution",
            "imageClick": "popup",
            "videoClick": "popup",
            "theme": "dark",
            "aspectRatio": "16/9",
        }

        self.assertEqual(len(self.camera_cards), 17)
        for card in self.camera_cards:
            self.assertEqual(
                {key: card.get(key) for key in expected},
                expected,
                card.get("id"),
            )
            self.assertNotIn("speakerOn", card)
            self.assertNotIn("microphoneOn", card)

    def test_event_reel_includes_all_cameras_and_opens_home_assistant(self):
        carousels = [
            node
            for node in self.nodes
            if node.get("type") == "custom:scrypted-nvr-events-carousel"
        ]

        self.assertEqual(len(carousels), 1)
        self.assertEqual(carousels[0].get("click"), "ha")
        self.assertNotIn("ids", carousels[0])

    def test_primary_and_secondary_camera_grids_share_exact_breakpoints(self):
        grids = [
            node
            for node in self.nodes
            if node.get("type") == "custom:layout-card"
            and node.get("layout_type") == "custom:grid-layout"
            and any(
                isinstance(child, dict)
                and child.get("type") == "custom:scrypted-nvr-camera"
                for child in walk(node)
            )
        ]

        self.assertEqual(len(grids), 2)
        for grid in grids:
            layout = grid["layout"]
            self.assertEqual(
                layout.get("grid-template-columns"),
                "repeat(4, minmax(0, 1fr))",
            )
            self.assertEqual(
                layout.get("mediaquery"),
                {
                    "(max-width: 1100px)": {
                        "grid-template-columns": "repeat(2, minmax(0, 1fr))"
                    },
                    "(max-width: 650px)": {
                        "grid-template-columns": "minmax(0, 1fr)"
                    },
                },
            )

    def test_navigation_destinations_are_exact(self):
        self.assertEqual(
            [
                node["navigation_path"]
                for node in self.nodes
                if isinstance(node.get("navigation_path"), str)
            ],
            EXPECTED_NAVIGATION_PATHS,
        )

    def test_yaml_contains_no_private_addresses_or_credential_markers(self):
        self.assertIsNone(RFC1918.search(self.text))
        lowered = self.text.casefold()
        for marker in CREDENTIAL_MARKERS:
            self.assertNotIn(marker, lowered)

    def test_yaml_contains_no_direct_stream_or_credential_bearing_urls(self):
        for match in URL.finditer(self.text):
            url = match.group(0)
            parsed = urllib_parse.urlsplit(url)
            self.assertNotIn(parsed.scheme.casefold(), {"rtsp", "rtsps"}, url)
            self.assertIsNone(parsed.username, url)
            self.assertIsNone(parsed.password, url)
            self.assertFalse(parsed.query, url)

    def test_private_rtsp_sources_use_only_generic_display_labels(self):
        self.assertIn("RTSP Camera A", self.text)
        self.assertIn("RTSP Camera B", self.text)
        self.assertNotIn("192.168.100.246", self.text)
        self.assertNotIn("192.168.40.90", self.text)


if __name__ == "__main__":
    unittest.main()
