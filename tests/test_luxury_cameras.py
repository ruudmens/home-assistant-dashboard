"""Contract tests for the responsive Luxury Cameras dashboard."""

from collections import Counter
from pathlib import Path
import re
import unittest

import yaml

from tests.config_assertions import load_config, walk


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = "dashboards/luxury_cameras.yaml"
EXPECTED_PRIMARY_PAIRS = [
    (107, "Front Door"),
    (266, "Back Yard"),
    (124, "Bedroom"),
    (268, "Living Room"),
]
EXPECTED_SECONDARY_PAIRS = [
    (267, "Back Yard 2"),
    (287, "Blink Backyard"),
    (286, "Blink Backyard 2"),
    (289, "GNT2 Camera"),
    (288, "Living Room 2"),
    (290, "Mini Camera"),
    (269, "OG Camera"),
    (250, "RTSP Camera A"),
    (264, "RTSP Camera B"),
    (171, "Tapo C211 A"),
    (173, "Tapo C211 B"),
    (270, "U1"),
    (271, "V4"),
]
EXPECTED_CAMERA_PAIRS = EXPECTED_PRIMARY_PAIRS + EXPECTED_SECONDARY_PAIRS
EXPECTED_CAMERA_IDS = {camera_id for camera_id, _label in EXPECTED_CAMERA_PAIRS}
EXPECTED_CAMERA_ORDER = [camera_id for camera_id, _label in EXPECTED_CAMERA_PAIRS]
EXPECTED_DISPLAY_LABELS = [label for _camera_id, label in EXPECTED_CAMERA_PAIRS]
EXPECTED_LIVE_IDS = [107, 266, 124, 268]
EXPECTED_NAVIGATION_PATHS = [
    "/luxury-home/home",
    "/luxury-garage/garage",
    "/luxury-remote/remote",
]
EXPECTED_HEADER_PHRASES = ("Luxury Cameras", "17 cameras", "Scrypted NVR")
RFC1918 = re.compile(
    r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
)
URL = re.compile(r"\b(?:https?|rtsps?)://[^\s\"'<>]+", re.IGNORECASE)
CREDENTIAL_MARKERS = (
    "webhook_secret",
    "access_token",
    "api_token",
    "private_key",
    "credentials",
    "credential",
    "bearer",
    "ha_token",
    "token",
    "password",
    "authorization",
    "api_key",
    "secret",
)
JWT_LIKE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
OPAQUE_SECRET_LIKE = re.compile(
    r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-]))"
    r"(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)"
    r"[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])"
)
FORBIDDEN_CONFIG_KEYS = {
    "areaid",
    "actions",
    "cameraaction",
    "cameracommand",
    "command",
    "commands",
    "deviceid",
    "entity",
    "entityid",
    "microphoneon",
    "pan",
    "performaction",
    "service",
    "speakeron",
    "target",
    "tilt",
    "zoom",
}
FORBIDDEN_CAMERA_KEY_FRAGMENTS = (
    "snapshot",
    "record",
    "ptz",
)


class CameraContractHelperTests(unittest.TestCase):
    def test_header_contract_requires_all_status_text_beyond_top_level_title(self):
        title_only = {
            "title": "Luxury Cameras",
            "views": [{"sections": []}],
        }
        section_header = {
            "title": "Luxury Cameras",
            "views": [
                {
                    "sections": [
                        {
                            "cards": [
                                {
                                    "type": "markdown",
                                    "content": "Luxury Cameras\n17 cameras\nScrypted NVR",
                                }
                            ]
                        }
                    ]
                }
            ],
        }

        self.assertEqual(matching_camera_headers(title_only), [])
        self.assertEqual(len(matching_camera_headers(section_header)), 1)

    def test_camera_pairing_requires_one_exact_label_and_camera_per_grid_item(self):
        valid_grid = {
            "type": "custom:layout-card",
            "layout_type": "custom:grid-layout",
            "cards": [
                {
                    "type": "vertical-stack",
                    "cards": [
                        {"type": "markdown", "content": "Front Door"},
                        {"type": "custom:scrypted-nvr-camera", "id": 107},
                    ],
                }
            ],
        }
        free_floating_label = {
            **valid_grid,
            "cards": [
                {"type": "custom:scrypted-nvr-camera", "id": 107},
                {"type": "markdown", "content": "Front Door"},
            ],
        }
        nested_mixed_grid = {
            **valid_grid,
            "cards": [{"type": "vertical-stack", "cards": [valid_grid]}],
        }

        self.assertEqual(camera_pairs_in_grid(valid_grid), [(107, "Front Door")])
        with self.assertRaises(ValueError):
            camera_pairs_in_grid(free_floating_label)
        with self.assertRaises(ValueError):
            camera_pairs_in_grid(nested_mixed_grid)

    def test_static_safety_checker_rejects_camera_side_actions_anywhere(self):
        unsafe_configs = [
            {"service": "camera.snapshot"},
            {"perform_action": "camera.record"},
            {"snapshot": True},
            {"recording": True},
            {"ptz": {"pan": "left"}},
            {"speakerOn": True},
            {"microphoneOn": True},
            {"hold_action": {"action": "call-service"}},
            {"target": {"device_id": "camera-device"}},
            {"click": "record"},
        ]

        for config in unsafe_configs:
            with self.subTest(config=config):
                self.assertTrue(
                    static_safety_violations(config, yaml.safe_dump(config))
                )

    def test_static_safety_checker_rejects_credentials_and_direct_urls(self):
        jwt_like = ".".join(("ey" + "J" * 20, "a" * 24, "b" * 24))
        opaque_secret = "camera" + "A1" * 16
        unsafe_texts = [
            "access_" + "token: example",
            "Bearer example",
            "HA_" + "TOKEN: example",
            "token=example",
            "token: example",
            "password: example",
            "authorization: example",
            "api_" + "key: example",
            jwt_like,
            opaque_secret,
            "rtsp://camera.example/live",
            "rtsps://camera.example/live",
            "https://ha.example/proxy/stream",
            "http://ha.example/proxy/stream",
        ]

        for text in unsafe_texts:
            with self.subTest(text=text[:24]):
                self.assertTrue(static_safety_violations({}, text))

    def test_static_safety_checker_allows_only_exact_relative_navigation(self):
        config = {
            "tap_action": {
                "action": "navigate",
                "navigation_path": "/luxury-home/home",
            }
        }

        self.assertEqual(
            static_safety_violations(config, yaml.safe_dump(config)),
            [],
        )
        self.assertTrue(
            static_safety_violations(
                {"navigation_path": "/not-approved"},
                "navigation_path: /not-approved",
            )
        )
        self.assertTrue(
            static_safety_violations(
                {"url": "//camera.example/live"},
                "url: //camera.example/live",
            )
        )


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


def camera_cards_in(value):
    """Return all Scrypted camera cards below *value* in traversal order."""
    return [
        node
        for node in walk(value)
        if isinstance(node, dict) and node.get("type") == "custom:scrypted-nvr-camera"
    ]


def camera_grids_in(config):
    """Return layout-card grids that contain at least one Scrypted camera."""
    return [
        node
        for node in walk(config)
        if isinstance(node, dict)
        and node.get("type") == "custom:layout-card"
        and node.get("layout_type") == "custom:grid-layout"
        and camera_cards_in(node)
    ]


def camera_pairs_in_grid(grid):
    """Pair one exact approved label with one camera in each direct grid item."""
    items = grid.get("cards")
    if not isinstance(items, list) or not items:
        raise ValueError("camera grid must have direct card items")
    pairs = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("camera grid item must be a mapping")
        nested_grids = [
            node
            for node in walk(item)
            if isinstance(node, dict)
            and node is not item
            and node.get("type") == "custom:layout-card"
            and node.get("layout_type") == "custom:grid-layout"
        ]
        cameras = camera_cards_in(item)
        labels = [
            label
            for label in EXPECTED_DISPLAY_LABELS
            if label in set(scalar_strings(item))
        ]
        if nested_grids or len(cameras) != 1 or len(labels) != 1:
            raise ValueError("camera grid items must pair one label with one camera")
        pairs.append((cameras[0].get("id"), labels[0]))
    return pairs


def header_regions(config):
    """Return structural regions that may contain the dashboard header."""
    views = config.get("views", [])
    if len(views) != 1 or not isinstance(views[0], dict):
        return []
    view = views[0]
    regions = []
    header = view.get("header")
    if isinstance(header, dict) and isinstance(header.get("card"), dict):
        regions.append(header["card"])
    regions.extend(
        section for section in view.get("sections", []) if isinstance(section, dict)
    )
    return regions


def matching_camera_headers(config):
    """Return structural header regions containing all approved status text."""
    return [
        region
        for region in header_regions(config)
        if all(
            phrase in "\n".join(scalar_strings(region))
            for phrase in EXPECTED_HEADER_PHRASES
        )
    ]


def normalized_key(value):
    """Normalize YAML keys for conservative camera-action detection."""
    return "".join(character for character in str(value).casefold() if character.isalnum())


def static_safety_violations(config, text):
    """Return unsafe actions, credentials, secrets, URLs, and paths in a config."""
    violations = []
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            normalized = normalized_key(key)
            if normalized in FORBIDDEN_CONFIG_KEYS or any(
                fragment in normalized for fragment in FORBIDDEN_CAMERA_KEY_FRAGMENTS
            ):
                violations.append(f"forbidden key {key!r}")
            if isinstance(key, str) and key.endswith("_action"):
                if key != "tap_action":
                    violations.append(f"forbidden action channel {key!r}")
                elif not isinstance(value, dict) or set(value) != {
                    "action",
                    "navigation_path",
                }:
                    violations.append("tap_action must be navigation only")
            if key == "action" and value != "navigate":
                violations.append(f"forbidden action {value!r}")
            if key in {"imageClick", "videoClick"} and (
                node.get("type") != "custom:scrypted-nvr-camera" or value != "popup"
            ):
                violations.append(f"unsafe camera click {key!r}")
            if key == "click" and (
                node.get("type") != "custom:scrypted-nvr-events-carousel" or value != "ha"
            ):
                violations.append("unsafe event click")

    lowered = text.casefold()
    for marker in CREDENTIAL_MARKERS:
        if marker in lowered:
            violations.append(f"credential marker {marker!r}")
    if JWT_LIKE.search(text):
        violations.append("JWT-like secret")
    if OPAQUE_SECRET_LIKE.search(text):
        violations.append("opaque token-like secret")
    if URL.search(text):
        violations.append("direct URL")

    for scalar in scalar_strings(config):
        if scalar.startswith("//"):
            violations.append(f"scheme-relative URL {scalar!r}")
        if scalar.startswith("/") and scalar not in EXPECTED_NAVIGATION_PATHS:
            violations.append(f"unapproved absolute path {scalar!r}")
        if "?" in scalar and scalar.startswith("/"):
            violations.append(f"query-bearing path {scalar!r}")
    return violations


class LuxuryCamerasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / CONFIG_PATH
        cls.text = cls.path.read_text(encoding="utf-8")
        cls.config = load_config(ROOT, CONFIG_PATH)
        cls.nodes = [node for node in walk(cls.config) if isinstance(node, dict)]
        cls.camera_cards = camera_cards_in(cls.config)
        cls.camera_grids = camera_grids_in(cls.config)

    def test_has_one_four_column_sections_camera_view(self):
        views = self.config["views"]

        self.assertEqual(len(views), 1)
        self.assertEqual(self.config.get("title"), "Luxury Cameras")
        self.assertEqual(views[0].get("title"), "Cameras")
        self.assertEqual(views[0].get("path"), "cameras")
        self.assertEqual(views[0].get("icon"), "mdi:cctv")
        self.assertEqual(views[0].get("type"), "sections")
        self.assertEqual(views[0].get("max_columns"), 4)
        self.assertIs(views[0].get("dense_section_placement"), True)

    def test_contains_real_header_and_exact_section_labels(self):
        headings = {
            node["heading"] for node in self.nodes if isinstance(node.get("heading"), str)
        }

        self.assertEqual(len(matching_camera_headers(self.config)), 1)
        self.assertTrue({"LIVE NOW", "ALL CAMERAS", "EVENT REEL"}.issubset(headings))

    def test_camera_ids_are_exact_and_unique(self):
        id_counts = Counter(card.get("id") for card in self.camera_cards)

        self.assertEqual(set(id_counts), EXPECTED_CAMERA_IDS)
        self.assertEqual(id_counts, Counter({camera_id: 1 for camera_id in EXPECTED_CAMERA_IDS}))
        self.assertEqual([card["id"] for card in self.camera_cards], EXPECTED_CAMERA_ORDER)

    def test_camera_grids_pair_exact_labels_ids_and_autoplay_split(self):
        self.assertEqual(len(self.camera_grids), 2)
        primary_grid, secondary_grid = self.camera_grids
        self.assertEqual(camera_pairs_in_grid(primary_grid), EXPECTED_PRIMARY_PAIRS)
        self.assertEqual(camera_pairs_in_grid(secondary_grid), EXPECTED_SECONDARY_PAIRS)

        primary_cards = camera_cards_in(primary_grid)
        secondary_cards = camera_cards_in(secondary_grid)
        self.assertEqual([card["id"] for card in primary_cards], EXPECTED_LIVE_IDS)
        self.assertTrue(all(card.get("live") is True for card in primary_cards))
        self.assertEqual(
            [card["id"] for card in secondary_cards],
            [camera_id for camera_id, _label in EXPECTED_SECONDARY_PAIRS],
        )
        self.assertTrue(all("live" not in card for card in secondary_cards))
        self.assertEqual(primary_cards + secondary_cards, self.camera_cards)

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
        self.assertEqual(len(self.camera_grids), 2)
        for grid in self.camera_grids:
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
        tap_actions = [node["tap_action"] for node in self.nodes if "tap_action" in node]

        self.assertEqual(
            [
                node["navigation_path"]
                for node in self.nodes
                if isinstance(node.get("navigation_path"), str)
            ],
            EXPECTED_NAVIGATION_PATHS,
        )
        self.assertEqual(
            tap_actions,
            [
                {"action": "navigate", "navigation_path": path}
                for path in EXPECTED_NAVIGATION_PATHS
            ],
        )

    def test_entire_yaml_is_action_url_and_credential_safe(self):
        self.assertIsNone(RFC1918.search(self.text))
        self.assertEqual(static_safety_violations(self.config, self.text), [])

    def test_private_rtsp_sources_use_only_generic_display_labels(self):
        self.assertIn("RTSP Camera A", self.text)
        self.assertIn("RTSP Camera B", self.text)
        self.assertNotIn("192.168.100.246", self.text)
        self.assertNotIn("192.168.40.90", self.text)


if __name__ == "__main__":
    unittest.main()
