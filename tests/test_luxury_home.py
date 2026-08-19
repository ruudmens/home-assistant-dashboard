"""Contract tests for the responsive Luxury Home dashboard."""

from pathlib import Path
import unittest

from tests.config_assertions import (
    assert_sections_view,
    cards_for_entity,
    load_config,
    referenced_entities,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "weather.home",
    "climate.my_ecobee",
    "sensor.my_ecobee_temperature",
    "sensor.my_ecobee_humidity",
    "scene.good_morning",
    "scene.i_m_back",
    "scene.all_lights",
    "scene.good_night",
    "scene.goodbye",
    "light.main_light",
    "light.kitchen_light",
    "light.bathroom_light",
    "light.doorway_light",
    "light.bedroom_light",
    "light.diningroom_light",
    "light.den_light_den_light",
    "light.closet_light",
    "light.garage_2",
    "sensor.envoy_202308085399_current_power_consumption",
    "sensor.envoy_202308085399_current_power_production",
    "sensor.envoy_202308085399_current_net_power_consumption",
    "sensor.envoy_202308085399_energy_consumption_today",
    "sensor.envoy_202308085399_energy_production_today",
    "media_player.living_room",
    "script.radio_play",
    "input_number.radio_volume",
    "alarm_control_panel.alarmo",
    "lock.level_lock_pro",
    "lock.back_door",
    "sensor.car_presence",
    "person.kcam",
}


class LuxuryHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT, "dashboards/luxury_home.yaml")

    def test_uses_two_column_responsive_sections(self):
        assert_sections_view(self, self.config, max_columns=2)

    def test_header_and_clock_use_native_lovelace_schema(self):
        view = self.config["views"][0]
        header = view["header"]
        self.assertIn("card", header)
        self.assertNotIn("cards", header)
        self.assertEqual(
            header["card"]["content"],
            "# Luxury Home\nA calm view of the people, comfort, and energy that make home.\n",
        )
        clock = next(
            card
            for section in view["sections"]
            for card in section["cards"]
            if card["type"] == "clock"
        )
        self.assertEqual(clock.get("clock_style"), "digital")
        self.assertNotIn("clock_type", clock)

    def test_clock_is_immediately_followed_by_the_date_card(self):
        cards = self.config["views"][0]["sections"][0]["cards"]
        clock_index = next(index for index, card in enumerate(cards) if card["type"] == "clock")
        date_card = cards[clock_index + 1]
        self.assertEqual(date_card["type"], "markdown")
        self.assertEqual(date_card["content"], "{{ now().strftime('%A, %B %-d') }}")
        self.assertIn("background: transparent;", date_card["card_mod"]["style"])
        self.assertIn("border: 0;", date_card["card_mod"]["style"])

    def test_sections_use_ordered_native_backgrounds(self):
        self.assertEqual(
            [
                {
                    "color": section["background"]["color"],
                    "opacity": section["background"]["opacity"],
                    "column_span": section.get("column_span"),
                }
                for section in self.config["views"][0]["sections"]
            ],
            [
                {"color": "#171a19", "opacity": 92, "column_span": 2},
                {"color": "#1c1a16", "opacity": 90, "column_span": 2},
                {"color": "#171a19", "opacity": 90, "column_span": None},
                {"color": "#1c1a16", "opacity": 90, "column_span": None},
                {"color": "#171a19", "opacity": 90, "column_span": None},
                {"color": "#1c1a16", "opacity": 90, "column_span": None},
                {"color": "#171a19", "opacity": 88, "column_span": 2},
            ],
        )

    def test_references_only_expected_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_referenced_entities_collects_strings_from_entities_lists(self):
        config = {
            "entities": [
                "sensor.out_of_scope",
                {"entity": "light.from_nested_map"},
                {"entity_id": "script.from_nested_map"},
                "not-an-entity",
            ]
        }
        self.assertEqual(
            referenced_entities(config),
            {"sensor.out_of_scope", "light.from_nested_map", "script.from_nested_map"},
        )

    def test_section_headings_are_in_design_order(self):
        self.assertEqual(
            [section["cards"][0]["heading"] for section in self.config["views"][0]["sections"]],
            [
                "At a glance",
                "Scenes",
                "Lighting",
                "Energy",
                "Media",
                "Security & presence",
                "Dashboards",
            ],
        )

    def test_scene_buttons_use_exact_actions_and_targets(self):
        scene_cards = self.config["views"][0]["sections"][1]["cards"][1:]
        self.assertEqual(
            [
                (
                    card["entity"],
                    card["tap_action"]["action"],
                    card["tap_action"]["perform_action"],
                    card["tap_action"]["target"]["entity_id"],
                )
                for card in scene_cards
            ],
            [
                ("scene.good_morning", "perform-action", "scene.turn_on", "scene.good_morning"),
                ("scene.i_m_back", "perform-action", "scene.turn_on", "scene.i_m_back"),
                ("scene.all_lights", "perform-action", "scene.turn_on", "scene.all_lights"),
                ("scene.good_night", "perform-action", "scene.turn_on", "scene.good_night"),
                ("scene.goodbye", "perform-action", "scene.turn_on", "scene.goodbye"),
            ],
        )

    def test_energy_cards_match_the_power_contract(self):
        cards = self.config["views"][0]["sections"][3]["cards"]
        self.assertEqual(
            [
                (card["entity"], card["name"], card["graph"], card["detail"])
                for card in cards
                if card["type"] == "sensor"
            ],
            [
                (
                    "sensor.envoy_202308085399_current_power_consumption",
                    "Consuming now",
                    "line",
                    2,
                ),
                (
                    "sensor.envoy_202308085399_current_power_production",
                    "Solar now",
                    "line",
                    2,
                ),
            ],
        )
        self.assertEqual(
            [(card["entity"], card["name"]) for card in cards if card["type"] == "tile"],
            [
                ("sensor.envoy_202308085399_current_net_power_consumption", "Net power"),
                ("sensor.envoy_202308085399_energy_consumption_today", "Used today"),
                ("sensor.envoy_202308085399_energy_production_today", "Produced today"),
            ],
        )
        history = next(card for card in cards if card["type"] == "history-graph")
        self.assertEqual(history["title"], "Power · last 12 hours")
        self.assertEqual(history["hours_to_show"], 12)
        self.assertEqual(
            [(entity["entity"], entity["name"]) for entity in history["entities"]],
            [
                ("sensor.envoy_202308085399_current_power_consumption", "Consumption"),
                ("sensor.envoy_202308085399_current_power_production", "Production"),
            ],
        )

    def test_radio_script_action_targets_itself(self):
        card = cards_for_entity(self.config, "script.radio_play")[0]
        self.assertEqual(
            card["tap_action"],
            {
                "action": "perform-action",
                "perform_action": "script.turn_on",
                "target": {"entity_id": "script.radio_play"},
            },
        )

    def test_security_controls_require_confirmation(self):
        for entity_id in (
            "alarm_control_panel.alarmo",
            "lock.level_lock_pro",
            "lock.back_door",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            self.assertTrue(
                all(card.get("tap_action", {}).get("confirmation") for card in cards),
                entity_id,
            )

    def test_security_actions_and_state_coloring_are_exact(self):
        alarm = cards_for_entity(self.config, "alarm_control_panel.alarmo")[0]
        self.assertEqual(alarm["tap_action"]["action"], "more-info")
        self.assertTrue(alarm["tap_action"]["confirmation"])
        self.assertEqual(
            {state["value"]: state["color"] for state in alarm["state"]},
            {
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
            },
        )
        expected_lock_states = {
            "locked": "#a7c7a0",
            "unlocked": "#d88d75",
            "open": "#d88d75",
            "jammed": "#d88d75",
            "locking": "#d5b77a",
            "unlocking": "#d5b77a",
            "unavailable": "#777972",
        }
        for entity_id in ("lock.level_lock_pro", "lock.back_door"):
            lock = cards_for_entity(self.config, entity_id)[0]
            self.assertEqual(lock["tap_action"]["action"], "toggle")
            self.assertTrue(lock["tap_action"]["confirmation"])
            self.assertEqual(
                {state["value"]: state["color"] for state in lock["state"]},
                expected_lock_states,
            )

    def test_security_status_cards_exist(self):
        security_cards = self.config["views"][0]["sections"][5]["cards"]
        self.assertIn(
            ("sensor.car_presence", "Car"),
            [(card.get("entity"), card.get("name")) for card in security_cards],
        )
        self.assertIn(
            ("person.kcam", "Kcam"),
            [(card.get("entity"), card.get("name")) for card in security_cards],
        )

    def test_dashboard_navigation_names_and_paths_are_exact(self):
        cards = self.config["views"][0]["sections"][6]["cards"][1:]
        self.assertEqual(
            [(card["name"], card["tap_action"]["navigation_path"]) for card in cards],
            [("Garage", "/luxury-garage"), ("Remote", "/luxury-remote")],
        )

    def test_lights_use_amber_color(self):
        for entity_id in sorted(entity for entity in EXPECTED if entity.startswith("light.")):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            self.assertTrue(all(card.get("color") == "amber" for card in cards), entity_id)

    def test_config_has_no_placeholder_or_out_of_scope_entities(self):
        serialized = str(self.config).lower()
        for forbidden in ("your_", "replace_me", "irrigation", "tesla"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
