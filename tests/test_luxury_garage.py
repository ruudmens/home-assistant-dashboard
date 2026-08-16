"""Contract tests for the safe Luxury Garage dashboard."""

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
    "light.garage_2",
    "binary_sensor.lumi_lumi_sensor_magnet_aq2_a84a2103_on_off",
    "binary_sensor.garage_motionsensor",
    "binary_sensor.garage_online",
    "sensor.lumi_lumi_sensor_magnet_aq2_power",
    "sensor.lumi_lumi_sensor_magnet_aq2_device_temperature",
    "script.1645405163026",
    "climate.my_ecobee",
    "sensor.my_ecobee_temperature",
}


class LuxuryGarageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT, "dashboards/luxury_garage.yaml")

    def test_uses_two_column_dense_sections(self):
        assert_sections_view(self, self.config, max_columns=2)

    def test_header_uses_a_singular_responsive_card(self):
        header = self.config["views"][0]["header"]
        self.assertEqual(header["layout"], "responsive")
        self.assertIn("card", header)
        self.assertNotIn("cards", header)

    def test_navigation_template_has_complete_luxury_styles(self):
        template = self.config["button_card_templates"]["luxury_nav"]
        self.assertFalse(template["show_state"])
        self.assertEqual(template["size"], "28px")
        self.assertEqual(
            template["styles"],
            {
                "card": [
                    {"border-radius": "18px"},
                    {"border": "1px solid rgba(213, 183, 122, 0.24)"},
                    {"background": "linear-gradient(145deg, rgba(36, 39, 37, 0.96), rgba(18, 20, 20, 0.96))"},
                    {"color": "#f6f3ec"},
                    {"padding": "16px"},
                ],
                "icon": [{"color": "#d5b77a"}],
                "name": [{"font-size": "13px"}, {"font-weight": 600}],
            },
        )

    def test_references_only_expected_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_garage_door_status_card_is_safe_and_state_colored(self):
        card = cards_for_entity(
            self.config, "binary_sensor.lumi_lumi_sensor_magnet_aq2_a84a2103_on_off"
        )[0]
        self.assertEqual(card["type"], "custom:button-card")
        self.assertTrue(card["show_state"])
        self.assertEqual(card["tap_action"]["action"], "more-info")
        self.assertNotIn("features", card)
        self.assertEqual(
            {state["value"]: state["color"] for state in card["state"]},
            {"off": "#a7c7a0", "on": "#d88d75", "unavailable": "#777972"},
        )

    def test_snapshot_is_the_sole_script_card_and_runs_itself(self):
        cards = cards_for_entity(self.config, "script.1645405163026")
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["type"], "button")
        self.assertEqual(
            card["tap_action"],
            {
                "action": "perform-action",
                "perform_action": "script.turn_on",
                "target": {"entity_id": "script.1645405163026"},
            },
        )

    def test_garage_light_uses_amber_color(self):
        cards = cards_for_entity(self.config, "light.garage_2")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["color"], "amber")

    def test_section_headings_and_backgrounds_are_in_design_order(self):
        sections = self.config["views"][0]["sections"]
        self.assertEqual(
            [section["cards"][0]["heading"] for section in sections],
            [
                "Garage door",
                "Controls",
                "Sensor health",
                "Home climate context",
                "Dashboards",
            ],
        )
        self.assertEqual(
            [
                (
                    section["background"]["color"],
                    section["background"]["opacity"],
                    section.get("column_span"),
                )
                for section in sections
            ],
            [
                ("#1c1a16", 92, 2),
                ("#171a19", 90, None),
                ("#1c1a16", 90, None),
                ("#171a19", 90, None),
                ("#171a19", 88, 2),
            ],
        )

    def test_dashboard_navigation_names_actions_and_paths_are_exact(self):
        cards = self.config["views"][0]["sections"][4]["cards"][1:]
        self.assertEqual(
            [
                (card["name"], card["tap_action"]["action"], card["tap_action"]["navigation_path"])
                for card in cards
            ],
            [
                ("Home", "navigate", "/luxury-home"),
                ("Remote", "navigate", "/luxury-remote"),
            ],
        )

    def test_status_markdown_explains_no_opener_and_no_controls_exist(self):
        serialized = str(self.config).lower()
        markdown = next(
            card["content"]
            for card in self.config["views"][0]["sections"][0]["cards"]
            if card["type"] == "markdown"
        )
        self.assertIn("No garage-door opener entity is available", markdown)
        for forbidden in ("open_garage", "close_garage", "cover.open_cover", "cover.close_cover"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
