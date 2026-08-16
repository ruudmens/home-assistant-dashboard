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
    "lock.virtual_front_door_lock",
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

    def test_references_only_expected_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_security_controls_require_confirmation(self):
        for entity_id in (
            "alarm_control_panel.alarmo",
            "lock.virtual_front_door_lock",
            "lock.back_door",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            self.assertTrue(
                all(card.get("tap_action", {}).get("confirmation") for card in cards),
                entity_id,
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
