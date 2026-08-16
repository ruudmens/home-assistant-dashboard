"""Contract tests for the phone-first Luxury Remote dashboard."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import yaml

from tests import config_assertions
from tests.config_assertions import (
    assert_sections_view,
    cards_for_entity,
    load_config,
    referenced_entities,
    unsafe_status_only_card_violations,
    walk,
)


ROOT = Path(__file__).resolve().parents[1]
REMOTE_PATH = "dashboards/luxury_remote.yaml"
EXPECTED = {
    "alarm_control_panel.alarmo",
    "lock.virtual_front_door_lock",
    "lock.back_door",
    "light.main_light",
    "light.kitchen_light",
    "light.bedroom_light",
    "light.garage_2",
    "scene.all_lights",
    "climate.my_ecobee",
    "weather.home",
    "media_player.living_room",
    "script.radio_play",
    "input_number.radio_volume",
    "person.kcam",
    "person.mom",
    "binary_sensor.livingroom_matter_pir_occupancy",
    "binary_sensor.zachary_s_s21_ultra_presence",
    "camera.livingroom_2",
    "camera.backyard_backyard_motion_snapshot",
    "camera.blink_backyard",
    "camera.bedroom_bedroom_motion_snapshot",
}

ALARM_COLORS = {
    "disarmed": "#a7c7a0",
    "armed_home": "#a7c7a0",
    "armed_away": "#a7c7a0",
    "armed_night": "#a7c7a0",
    "armed_vacation": "#a7c7a0",
    "armed_custom_bypass": "#a7c7a0",
    "arming": "#d5b77a",
    "pending": "#d5b77a",
    "disarming": "#d5b77a",
    "triggered": "#d88d75",
    "unavailable": "#777972",
    "unknown": "#777972",
}
LOCK_COLORS = {
    "locked": "#a7c7a0",
    "unlocked": "#d88d75",
    "open": "#d88d75",
    "jammed": "#d88d75",
    "locking": "#d5b77a",
    "unlocking": "#d5b77a",
    "opening": "#d5b77a",
    "unavailable": "#777972",
    "unknown": "#777972",
}


def card_inventory(config: dict) -> list[tuple[str, str | None, str | None, str | None, str | None]]:
    """Return the exact presentation fields for every recursive Lovelace card."""
    return [
        (path, card.get("type"), card.get("entity"), card.get("name"), card.get("heading"))
        for path, card in config_assertions.iter_lovelace_cards(config)
    ]


def action_record(
    path: str,
    channel: str,
    action: str,
    *,
    perform_action: str | None = None,
    service: str | None = None,
    entity_id: str | None = None,
    device_id: str | None = None,
    area_id: str | None = None,
    navigation_path: str | None = None,
    confirmation: bool = False,
) -> dict:
    """Build a complete expected explicit-action record."""
    return {
        "path": path,
        "channel": channel,
        "action": action,
        "perform_action": perform_action,
        "service": service,
        "target_entity_id": entity_id,
        "target_device_id": device_id,
        "target_area_id": area_id,
        "navigation_path": navigation_path,
        "has_confirmation": confirmation,
    }


EXACT_CARD_INVENTORY = [
    ("views[0].sections[0].cards[0]", "heading", None, None, "Security"),
    ("views[0].sections[0].cards[1]", "custom:button-card", "alarm_control_panel.alarmo", "Alarmo", None),
    ("views[0].sections[0].cards[2]", "custom:button-card", "lock.virtual_front_door_lock", "Front door", None),
    ("views[0].sections[0].cards[3]", "custom:button-card", "lock.back_door", "Back door", None),
    ("views[0].sections[1].cards[0]", "heading", None, None, "Quick lights"),
    ("views[0].sections[1].cards[1]", "tile", "light.main_light", "Main", None),
    ("views[0].sections[1].cards[2]", "tile", "light.kitchen_light", "Kitchen", None),
    ("views[0].sections[1].cards[3]", "tile", "light.bedroom_light", "Bedroom", None),
    ("views[0].sections[1].cards[4]", "tile", "light.garage_2", "Garage", None),
    ("views[0].sections[1].cards[5]", "button", "scene.all_lights", "All Lights", None),
    ("views[0].sections[2].cards[0]", "heading", None, None, "Comfort"),
    ("views[0].sections[2].cards[1]", "thermostat", "climate.my_ecobee", "Ecobee", None),
    ("views[0].sections[2].cards[2]", "weather-forecast", "weather.home", None, None),
    ("views[0].sections[3].cards[0]", "heading", None, None, "Media"),
    ("views[0].sections[3].cards[1]", "media-control", "media_player.living_room", None, None),
    ("views[0].sections[3].cards[2]", "custom:stack-in-card", None, None, None),
    ("views[0].sections[3].cards[2].cards[0]", "tile", "script.radio_play", "GKR Radio", None),
    ("views[0].sections[3].cards[2].cards[1]", "tile", "input_number.radio_volume", "Radio volume", None),
    ("views[0].sections[4].cards[0]", "heading", None, None, "People & presence"),
    ("views[0].sections[4].cards[1]", "tile", "person.kcam", "Kcam", None),
    ("views[0].sections[4].cards[2]", "tile", "person.mom", "Mom", None),
    ("views[0].sections[4].cards[3]", "tile", "binary_sensor.livingroom_matter_pir_occupancy", "Living Room occupancy", None),
    ("views[0].sections[4].cards[4]", "tile", "binary_sensor.zachary_s_s21_ultra_presence", "Zachary presence", None),
    ("views[0].sections[5].cards[0]", "heading", None, None, "Cameras"),
    ("views[0].sections[5].cards[1]", "picture-entity", "camera.livingroom_2", "Living Room", None),
    ("views[0].sections[5].cards[2]", "picture-entity", "camera.backyard_backyard_motion_snapshot", "Backyard snapshot", None),
    ("views[0].sections[5].cards[3]", "picture-entity", "camera.blink_backyard", "Blink Backyard", None),
    ("views[0].sections[5].cards[4]", "picture-entity", "camera.bedroom_bedroom_motion_snapshot", "Bedroom snapshot", None),
    ("views[0].sections[6].cards[0]", "heading", None, None, "Dashboards"),
    ("views[0].sections[6].cards[1]", "custom:button-card", None, "Home", None),
    ("views[0].sections[6].cards[2]", "custom:button-card", None, "Garage", None),
]

EXACT_ACTION_RECORDS = [
    action_record(
        "views[0].sections[0].cards[1]", "tap_action", "more-info", confirmation=True
    ),
    action_record(
        "views[0].sections[0].cards[2]", "tap_action", "toggle", confirmation=True
    ),
    action_record(
        "views[0].sections[0].cards[3]", "tap_action", "toggle", confirmation=True
    ),
    action_record(
        "views[0].sections[1].cards[5]",
        "tap_action",
        "perform-action",
        perform_action="scene.turn_on",
        entity_id="scene.all_lights",
    ),
    action_record(
        "views[0].sections[3].cards[2].cards[0]",
        "tap_action",
        "perform-action",
        perform_action="script.turn_on",
        entity_id="script.radio_play",
    ),
    action_record("views[0].sections[5].cards[1]", "tap_action", "more-info"),
    action_record("views[0].sections[5].cards[2]", "tap_action", "more-info"),
    action_record("views[0].sections[5].cards[3]", "tap_action", "more-info"),
    action_record("views[0].sections[5].cards[4]", "tap_action", "more-info"),
    action_record(
        "views[0].sections[6].cards[1]",
        "tap_action",
        "navigate",
        navigation_path="/luxury-home",
    ),
    action_record(
        "views[0].sections[6].cards[2]",
        "tap_action",
        "navigate",
        navigation_path="/luxury-garage",
    ),
]


class LuxuryRemoteTests(unittest.TestCase):
    def test_dashboard_file_must_exist_before_loading_configuration(self):
        missing_path = "dashboards/does_not_exist.yaml"
        with self.assertRaises(FileNotFoundError):
            load_config(ROOT, missing_path)

    def test_load_config_rejects_duplicate_yaml_mapping_keys(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            duplicate_config = Path(temporary_directory) / "duplicate.yaml"
            duplicate_config.write_text("title: First\ntitle: Second\n", encoding="utf-8")
            with self.assertRaisesRegex(yaml.constructor.ConstructorError, "duplicate mapping key"):
                load_config(duplicate_config.parent, duplicate_config.name)

    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT, REMOTE_PATH)
        cls.view = cls.config["views"][0]

    def test_uses_one_phone_first_dense_sections_view(self):
        self.assertEqual(self.config["title"], "Luxury Remote")
        self.assertEqual(
            (self.view["title"], self.view["path"], self.view["icon"]),
            ("Remote", "remote", "mdi:remote"),
        )
        assert_sections_view(self, self.config, max_columns=1)
        self.assertTrue(self.view["dense_section_placement"])

    def test_header_is_a_single_responsive_two_line_markdown_card(self):
        header = self.view["header"]
        self.assertEqual(header["layout"], "responsive")
        self.assertIn("card", header)
        self.assertNotIn("cards", header)
        self.assertEqual(header["card"]["type"], "markdown")
        self.assertEqual(
            header["card"]["content"],
            "# Luxury Remote\nThe most useful controls, ordered for one-handed access.\n",
        )
        self.assertEqual(
            header["card"]["card_mod"]["style"],
            "ha-card {\n  background: transparent;\n  border: 0;\n  color: #f6f3ec;\n}\n",
        )

    def test_references_the_exact_remote_entity_set(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_entity_references_have_the_exact_global_occurrence_counts(self):
        expected_counts = {entity_id: 1 for entity_id in EXPECTED}
        expected_counts.update({"scene.all_lights": 2, "script.radio_play": 2})
        self.assertEqual(config_assertions.referenced_entity_counts(self.config), expected_counts)

        duplicate_scene = deepcopy(self.config)
        duplicate_scene["views"][0]["sections"][1]["cards"].append(
            deepcopy(cards_for_entity(duplicate_scene, "scene.all_lights")[0])
        )
        self.assertNotEqual(
            config_assertions.referenced_entity_counts(duplicate_scene), expected_counts
        )

    def test_security_cards_have_confirmed_exact_actions_and_state_colors(self):
        expected_actions = {
            "alarm_control_panel.alarmo": (
                "Alarmo",
                "more-info",
                "Security",
                "Open alarm controls?",
            ),
            "lock.virtual_front_door_lock": (
                "Front door",
                "toggle",
                "Front door",
                "Change the front door lock state?",
            ),
            "lock.back_door": (
                "Back door",
                "toggle",
                "Back door",
                "Change the back door lock state?",
            ),
        }
        for entity_id, (name, action, title, text) in expected_actions.items():
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            self.assertTrue(all(card.get("tap_action", {}).get("confirmation") for card in cards))
            self.assertTrue(all(card.get("type") == "custom:button-card" for card in cards))
            self.assertTrue(all(card.get("show_state") is True for card in cards))
            card = cards[0]
            self.assertEqual(card["name"], name)
            self.assertEqual(card["tap_action"]["action"], action)
            self.assertEqual(card["tap_action"]["confirmation"], {"title": title, "text": text})
        alarm = cards_for_entity(self.config, "alarm_control_panel.alarmo")[0]
        self.assertEqual({state["value"]: state["color"] for state in alarm["state"]}, ALARM_COLORS)
        for entity_id in ("lock.virtual_front_door_lock", "lock.back_door"):
            lock = cards_for_entity(self.config, entity_id)[0]
            self.assertEqual({state["value"]: state["color"] for state in lock["state"]}, LOCK_COLORS)

    def test_security_cards_have_no_unconfirmed_or_unsupported_action_channels(self):
        for entity_id in (
            "alarm_control_panel.alarmo",
            "lock.virtual_front_door_lock",
            "lock.back_door",
        ):
            self.assertEqual(
                config_assertions.security_action_violations(cards_for_entity(self.config, entity_id)[0]),
                [],
                entity_id,
            )

        unsafe_lock = deepcopy(cards_for_entity(self.config, "lock.virtual_front_door_lock")[0])
        unsafe_lock["hold_action"] = {"action": "toggle"}
        self.assertIn(
            "hold_action action 'toggle' requires confirmation",
            config_assertions.security_action_violations(unsafe_lock),
        )

        unconfirmed_more_info = deepcopy(cards_for_entity(self.config, "lock.back_door")[0])
        unconfirmed_more_info["hold_action"] = {"action": "more-info"}
        self.assertIn(
            "hold_action action 'more-info' requires confirmation",
            config_assertions.security_action_violations(unconfirmed_more_info),
        )

    def test_quick_lights_are_sole_amber_cards_and_scene_targets_itself(self):
        expected_lights = {
            "light.main_light": "Main",
            "light.kitchen_light": "Kitchen",
            "light.bedroom_light": "Bedroom",
            "light.garage_2": "Garage",
        }
        for entity_id, name in expected_lights.items():
            cards = cards_for_entity(self.config, entity_id)
            self.assertEqual(len(cards), 1, entity_id)
            self.assertEqual(cards[0]["type"], "tile")
            self.assertEqual(cards[0]["name"], name)
            self.assertEqual(cards[0]["color"], "amber")
        scene = cards_for_entity(self.config, "scene.all_lights")[0]
        self.assertEqual(
            (scene["type"], scene["name"], scene["icon"]),
            ("button", "All Lights", "mdi:lightbulb-group"),
        )
        self.assertEqual(
            scene["tap_action"],
            {
                "action": "perform-action",
                "perform_action": "scene.turn_on",
                "target": {"entity_id": "scene.all_lights"},
            },
        )

    def test_section_headings_and_phone_backgrounds_are_in_exact_order(self):
        sections = self.view["sections"]
        self.assertTrue(all(section["type"] == "grid" for section in sections))
        self.assertEqual([len(section["cards"]) for section in sections], [4, 6, 3, 3, 5, 5, 3])
        self.assertEqual(
            [section["cards"][0]["heading"] for section in sections],
            [
                "Security",
                "Quick lights",
                "Comfort",
                "Media",
                "People & presence",
                "Cameras",
                "Dashboards",
            ],
        )
        self.assertEqual(
            [(section["background"]["color"], section["background"]["opacity"]) for section in sections],
            [
                ("#1c1a16", 92),
                ("#171a19", 90),
                ("#1c1a16", 90),
                ("#171a19", 90),
                ("#1c1a16", 90),
                ("#171a19", 90),
                ("#171a19", 88),
            ],
        )
        self.assertTrue(all("column_span" not in section for section in sections))

    def test_recursive_card_inventory_is_exact_and_rejects_nested_markdown(self):
        self.assertEqual(card_inventory(self.config), EXACT_CARD_INVENTORY)

        nested_markdown = deepcopy(self.config)
        nested_markdown["views"][0]["sections"][3]["cards"][2]["cards"].append(
            {"type": "markdown", "content": "Unrelated nested card"}
        )
        self.assertNotEqual(card_inventory(nested_markdown), EXACT_CARD_INVENTORY)

        singular_wrapper = deepcopy(self.config)
        singular_wrapper["views"][0]["sections"][3]["cards"][1]["card"] = {
            "type": "markdown",
            "content": "Wrapped card",
        }
        wrapper_inventory = card_inventory(singular_wrapper)
        self.assertNotEqual(wrapper_inventory, EXACT_CARD_INVENTORY)
        self.assertIn(
            ("views[0].sections[3].cards[1].card", "markdown", None, None, None),
            wrapper_inventory,
        )

    def test_explicit_action_records_are_exact_and_reject_nested_device_target(self):
        self.assertEqual(config_assertions.explicit_action_records(self.config), EXACT_ACTION_RECORDS)

        nested_device_target = deepcopy(self.config)
        nested_device_target["views"][0]["sections"][3]["cards"][2]["cards"].append(
            {
                "type": "button",
                "entity": "script.radio_play",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "script.turn_on",
                    "target": {"device_id": "living-room-device"},
                },
            }
        )
        self.assertEqual(config_assertions.action_contract_violations(nested_device_target), [])
        self.assertNotEqual(
            config_assertions.explicit_action_records(nested_device_target), EXACT_ACTION_RECORDS
        )

    def test_embedded_custom_field_actions_are_in_the_exact_recursive_inventory(self):
        custom_field_device_target = deepcopy(self.config)
        custom_field_device_target["views"][0]["sections"][0]["cards"][1]["custom_fields"] = {
            "danger": {
                "card": {
                    "type": "button",
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "script.turn_on",
                        "target": {"device_id": "unrelated-device"},
                    },
                }
            }
        }
        self.assertEqual(config_assertions.action_contract_violations(custom_field_device_target), [])
        custom_field_inventory = card_inventory(custom_field_device_target)
        self.assertNotEqual(custom_field_inventory, EXACT_CARD_INVENTORY)
        self.assertIn(
            (
                "views[0].sections[0].cards[1].custom_fields.danger.card",
                "button",
                None,
                None,
                None,
            ),
            custom_field_inventory,
        )
        custom_field_actions = config_assertions.explicit_action_records(custom_field_device_target)
        self.assertNotEqual(
            custom_field_actions, EXACT_ACTION_RECORDS
        )
        self.assertIn(
            action_record(
                "views[0].sections[0].cards[1].custom_fields.danger.card",
                "tap_action",
                "perform-action",
                perform_action="script.turn_on",
                device_id="unrelated-device",
            ),
            custom_field_actions,
        )

    def test_recursive_card_iterator_deduplicates_overlapping_embedded_cards(self):
        overlapping_cards = deepcopy(self.config)
        shared_card = {"type": "markdown", "content": "Shared card"}
        alarmo = overlapping_cards["views"][0]["sections"][0]["cards"][1]
        alarmo["card"] = shared_card
        alarmo["custom_fields"] = {"danger": {"card": shared_card}}
        shared_inventory = [
            card for card in card_inventory(overlapping_cards) if card[1] == "markdown"
        ]
        self.assertEqual(
            shared_inventory,
            [("views[0].sections[0].cards[1].card", "markdown", None, None, None)],
        )

    def test_comfort_uses_ecobee_thermostat_and_compact_daily_weather(self):
        thermostat = cards_for_entity(self.config, "climate.my_ecobee")[0]
        self.assertEqual((thermostat["type"], thermostat["name"]), ("thermostat", "Ecobee"))
        weather = cards_for_entity(self.config, "weather.home")[0]
        self.assertEqual(weather["type"], "weather-forecast")
        self.assertEqual(weather["forecast_type"], "daily")
        self.assertFalse(weather["show_forecast"])

    def test_media_controls_and_radio_actions_are_exact(self):
        media = cards_for_entity(self.config, "media_player.living_room")[0]
        self.assertEqual(media["type"], "media-control")
        radio = cards_for_entity(self.config, "script.radio_play")[0]
        self.assertEqual((radio["type"], radio["name"], radio["icon"]), ("tile", "GKR Radio", "mdi:radio"))
        self.assertEqual(
            radio["tap_action"],
            {
                "action": "perform-action",
                "perform_action": "script.turn_on",
                "target": {"entity_id": "script.radio_play"},
            },
        )
        volume = cards_for_entity(self.config, "input_number.radio_volume")[0]
        self.assertEqual((volume["type"], volume["name"]), ("tile", "Radio volume"))

    def test_people_and_presence_cards_have_exact_entities_and_names(self):
        people_cards = self.view["sections"][4]["cards"][1:]
        self.assertEqual(
            [(card["type"], card["entity"], card["name"]) for card in people_cards],
            [
                ("tile", "person.kcam", "Kcam"),
                ("tile", "person.mom", "Mom"),
                ("tile", "binary_sensor.livingroom_matter_pir_occupancy", "Living Room occupancy"),
                ("tile", "binary_sensor.zachary_s_s21_ultra_presence", "Zachary presence"),
            ],
        )

    def test_camera_cards_are_safe_status_only_picture_entities(self):
        camera_cards = self.view["sections"][5]["cards"][1:]
        self.assertEqual(
            [(card["entity"], card["name"]) for card in camera_cards],
            [
                ("camera.livingroom_2", "Living Room"),
                ("camera.backyard_backyard_motion_snapshot", "Backyard snapshot"),
                ("camera.blink_backyard", "Blink Backyard"),
                ("camera.bedroom_bedroom_motion_snapshot", "Bedroom snapshot"),
            ],
        )
        for card in camera_cards:
            self.assertEqual(len(cards_for_entity(self.config, card["entity"])), 1)
            self.assertEqual(card["type"], "picture-entity")
            self.assertEqual(card["camera_view"], "auto")
            self.assertFalse(card["show_state"])
            self.assertEqual(card["tap_action"]["action"], "more-info")
            self.assertEqual(unsafe_status_only_card_violations(card), [])

    def test_camera_status_safety_rejects_an_actionable_hold_mutant(self):
        camera = cards_for_entity(self.config, "camera.livingroom_2")[0]
        mutant = deepcopy(camera)
        mutant["hold_action"] = {
            "action": "perform-action",
            "perform_action": "camera.snapshot",
        }
        self.assertIn(
            "hold_action action 'perform-action' is unsafe",
            unsafe_status_only_card_violations(mutant),
        )

    def test_dashboard_navigation_names_actions_and_paths_are_exact(self):
        cards = self.view["sections"][6]["cards"][1:]
        self.assertEqual(
            [(card["name"], card["tap_action"]["action"], card["tap_action"]["navigation_path"]) for card in cards],
            [("Home", "navigate", "/luxury-home"), ("Garage", "navigate", "/luxury-garage")],
        )

    def test_navigation_template_uses_the_phone_luxury_style(self):
        template = self.config["button_card_templates"]["luxury_nav"]
        self.assertFalse(template["show_state"])
        self.assertEqual(template["size"], "27px")
        self.assertEqual(template["styles"]["card"], [
            {"border-radius": "18px"},
            {"border": "1px solid rgba(213, 183, 122, 0.24)"},
            {"background": "linear-gradient(145deg, rgba(36, 39, 37, 0.96), rgba(18, 20, 20, 0.96))"},
            {"color": "#f6f3ec"},
            {"padding": "15px"},
        ])
        self.assertEqual(template["styles"]["icon"], [{"color": "#d5b77a"}])
        self.assertEqual(template["styles"]["name"], [{"font-size": "13px"}, {"font-weight": 600}])

    def test_config_has_no_irrigation_or_source_placeholders(self):
        serialized = str(self.config).lower()
        self.assertFalse(any("irrigation" in str(node).lower() for node in walk(self.config)))
        for forbidden in ("your_", "replace_me", "irrigation", "source"):
            self.assertNotIn(forbidden, serialized)

    def test_global_actions_use_only_the_explicit_remote_allowlist(self):
        self.assertEqual(config_assertions.action_contract_violations(self.config), [])

        restart_mutant = deepcopy(self.config)
        restart_mutant["views"][0]["sections"][0]["cards"][1]["hold_action"] = {
            "action": "perform-action",
            "perform_action": "homeassistant.restart",
        }
        self.assertIn(
            "perform_action 'homeassistant.restart' is not allowed",
            config_assertions.action_contract_violations(restart_mutant),
        )

        unsupported_action_mutant = deepcopy(self.config)
        unsupported_action_mutant["views"][0]["sections"][0]["cards"][1]["hold_action"] = {
            "action": "call-service"
        }
        self.assertIn(
            "action 'call-service' is not allowed",
            config_assertions.action_contract_violations(unsupported_action_mutant),
        )

    def test_config_has_no_credentials_and_rejects_normalized_credential_mutants(self):
        self.assertEqual(config_assertions.credential_hygiene_violations(self.config), [])

        expected_key_markers = {
            "access_token": "access_token",
            "api_token": "api_token",
            "private-key": "private_key",
            "credentials": "credentials",
            "webhookSecret": "webhook_secret",
        }
        for key, marker in expected_key_markers.items():
            credential_mutant = deepcopy(self.config)
            credential_mutant[key] = "private-value"
            self.assertIn(
                f"credential marker '{marker}' found in key '{key}'",
                config_assertions.credential_hygiene_violations(credential_mutant),
            )

        content_mutant = deepcopy(self.config)
        content_mutant["note"] = "PRIVATE KEY"
        self.assertIn(
            "credential marker 'private_key' found in string 'PRIVATE KEY'",
            config_assertions.credential_hygiene_violations(content_mutant),
        )


if __name__ == "__main__":
    unittest.main()
