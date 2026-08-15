# Responsive Luxury Home Assistant Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, deploy, and verify three additive responsive Home Assistant dashboards using the user's live entities while preserving every existing dashboard.

**Architecture:** Keep each Lovelace dashboard as a reviewable YAML file in the repository, with a small manifest describing its storage-mode registration. A tested Python WebSocket deployer performs collision checks, live entity/resource preflight, atomic create/save/read-back operations, and rollback of only dashboards created by the current run.

**Tech Stack:** Home Assistant Lovelace YAML, Sections views, button-card/card-mod/stack-in-card, Python 3, PyYAML, websocket-client, unittest, Home Assistant WebSocket API.

---

## File map

- `dashboards/luxury_home.yaml` — responsive whole-home dashboard configuration.
- `dashboards/luxury_garage.yaml` — responsive garage status and controls.
- `dashboards/luxury_remote.yaml` — phone-first remote configuration.
- `tools/dashboard_manifest.yaml` — dashboard registration metadata and source-file mapping.
- `tools/__init__.py` — makes deployment utilities importable in tests.
- `tools/deploy_dashboards.py` — authenticated preflight, deployment, read-back, and rollback client.
- `tests/config_assertions.py` — reusable Lovelace configuration assertions.
- `tests/__init__.py` — makes the local test suite importable without package-name collisions.
- `tests/test_dashboard_manifest.py` — manifest contract tests.
- `tests/test_luxury_home.py` — Home entity, safety, and responsive-layout tests.
- `tests/test_luxury_garage.py` — Garage entity and non-control safety tests.
- `tests/test_luxury_remote.py` — Remote entity, confirmation, and mobile-layout tests.
- `tests/test_deploy_dashboards.py` — WebSocket deployment and rollback unit tests.
- `requirements-dashboard.txt` — bounded Python runtime dependencies.
- `.gitignore` — excludes credential-free deployment evidence under `artifacts/`.
- `README.md` — documents generation, dry-run, deployment, and rollback usage.

### Task 1: Establish the dashboard manifest contract

**Files:**
- Create: `requirements-dashboard.txt`
- Create: `tools/__init__.py`
- Create: `tools/dashboard_manifest.yaml`
- Create: `tests/__init__.py`
- Create: `tests/test_dashboard_manifest.py`

- [ ] **Step 1: Write the failing manifest test**

Create `tests/test_dashboard_manifest.py`:

```python
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "dashboard_manifest.yaml"


class DashboardManifestTests(unittest.TestCase):
    def test_manifest_registers_exactly_three_additive_dashboards(self):
        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        dashboards = data["dashboards"]
        self.assertEqual(
            [item["url_path"] for item in dashboards],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )
        self.assertEqual(
            [item["title"] for item in dashboards],
            ["Luxury Home", "Luxury Garage", "Luxury Remote"],
        )
        self.assertTrue(all(item["mode"] == "storage" for item in dashboards))
        self.assertTrue(all(item["show_in_sidebar"] for item in dashboards))
        self.assertTrue(all(not item["require_admin"] for item in dashboards))
        self.assertEqual(
            {item["config"] for item in dashboards},
            {
                "dashboards/luxury_home.yaml",
                "dashboards/luxury_garage.yaml",
                "dashboards/luxury_remote.yaml",
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing manifest failure**

Run:

```powershell
python -m unittest tests.test_dashboard_manifest -v
```

Expected: `ERROR` with `FileNotFoundError` for `tools/dashboard_manifest.yaml`.

- [ ] **Step 3: Add bounded dependencies, package markers, and the exact manifest**

Create `requirements-dashboard.txt`:

```text
PyYAML>=6.0,<7
websocket-client>=1.8,<2
```

Create `tools/__init__.py`:

```python
"""Dashboard deployment utilities."""
```

Create `tests/__init__.py`:

```python
"""Dashboard configuration and deployment tests."""
```

Create `tools/dashboard_manifest.yaml`:

```yaml
dashboards:
  - url_path: luxury-home
    title: Luxury Home
    icon: mdi:home-heart
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/luxury_home.yaml
  - url_path: luxury-garage
    title: Luxury Garage
    icon: mdi:garage
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/luxury_garage.yaml
  - url_path: luxury-remote
    title: Luxury Remote
    icon: mdi:remote
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/luxury_remote.yaml
```

- [ ] **Step 4: Install dependencies and run the manifest test**

Run:

```powershell
python -m pip install -r requirements-dashboard.txt
python -m unittest tests.test_dashboard_manifest -v
```

Expected: one test passes.

- [ ] **Step 5: Commit the manifest contract**

```powershell
git add requirements-dashboard.txt tools/__init__.py tools/dashboard_manifest.yaml tests/__init__.py tests/test_dashboard_manifest.py
git commit -m "test: define luxury dashboard manifest"
```

### Task 2: Build the responsive Luxury Home configuration

**Files:**
- Create: `tests/config_assertions.py`
- Create: `tests/test_luxury_home.py`
- Create: `dashboards/luxury_home.yaml`

- [ ] **Step 1: Add reusable configuration assertions**

Create `tests/config_assertions.py`:

```python
from pathlib import Path
import re

import yaml


ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def load_config(root: Path, relative_path: str) -> dict:
    return yaml.safe_load((root / relative_path).read_text(encoding="utf-8"))


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def referenced_entities(config: dict) -> set[str]:
    found = set()
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key in ("entity", "entity_id"):
            value = node.get(key)
            values = value if isinstance(value, list) else [value]
            for candidate in values:
                if isinstance(candidate, str) and ENTITY_ID.fullmatch(candidate):
                    found.add(candidate)
    return found


def cards_for_entity(config: dict, entity_id: str) -> list[dict]:
    return [
        node
        for node in walk(config)
        if isinstance(node, dict) and node.get("entity") == entity_id
    ]


def assert_sections_view(testcase, config: dict, max_columns: int):
    testcase.assertIn("views", config)
    testcase.assertEqual(len(config["views"]), 1)
    view = config["views"][0]
    testcase.assertEqual(view["type"], "sections")
    testcase.assertEqual(view["max_columns"], max_columns)
    testcase.assertTrue(view["dense_section_placement"])
    testcase.assertGreater(len(view["sections"]), 0)
```

- [ ] **Step 2: Write the failing Home dashboard tests**

Create `tests/test_luxury_home.py`:

```python
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

    def test_uses_responsive_two_column_sections(self):
        assert_sections_view(self, self.config, max_columns=2)

    def test_references_only_the_approved_home_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_lock_and_alarm_entry_points_require_confirmation(self):
        for entity_id in (
            "alarm_control_panel.alarmo",
            "lock.virtual_front_door_lock",
            "lock.back_door",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            for card in cards:
                self.assertIn("confirmation", card["tap_action"], entity_id)

    def test_active_lights_use_the_warm_accent(self):
        for entity_id in sorted(entity for entity in EXPECTED if entity.startswith("light.")):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            self.assertTrue(all(card.get("color") == "amber" for card in cards), entity_id)

    def test_contains_no_source_placeholders(self):
        rendered = str(self.config).lower()
        for placeholder in ("your_", "replace_me", "irrigation", "tesla"):
            self.assertNotIn(placeholder, rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the Home tests and verify the missing file failure**

Run:

```powershell
python -m unittest tests.test_luxury_home -v
```

Expected: `ERROR` with `FileNotFoundError` for `dashboards/luxury_home.yaml`.

- [ ] **Step 4: Create the complete Luxury Home configuration**

Create `dashboards/luxury_home.yaml`:

```yaml
title: Luxury Home
button_card_templates:
  luxury_nav:
    show_state: false
    size: 28px
    styles:
      card:
        - border-radius: 18px
        - border: 1px solid rgba(213, 183, 122, 0.24)
        - background: linear-gradient(145deg, rgba(36, 39, 37, 0.96), rgba(18, 20, 20, 0.96))
        - color: '#f6f3ec'
        - padding: 16px
      icon:
        - color: '#d5b77a'
      name:
        - font-size: 13px
        - font-weight: 600
views:
  - title: Home
    path: home
    icon: mdi:home-heart
    type: sections
    max_columns: 2
    dense_section_placement: true
    header:
      layout: responsive
      badges_position: bottom
      card:
        type: markdown
        content: |
          # Luxury Home
          A calm view of the people, comfort, and energy that make home.
        card_mod:
          style: |
            ha-card {
              background: transparent;
              border: 0;
              color: #f6f3ec;
            }
    sections:
      - type: grid
        column_span: 2
        background:
          color: '#171a19'
          opacity: 92
        cards:
          - type: heading
            heading: At a glance
            icon: mdi:weather-partly-cloudy
          - type: clock
            clock_style: digital
            clock_size: large
            show_seconds: false
            time_format: '12'
            no_background: true
          - type: weather-forecast
            entity: weather.home
            forecast_type: daily
            show_forecast: true
          - type: tile
            entity: climate.my_ecobee
            name: Home climate
            tap_action:
              action: more-info
          - type: tile
            entity: sensor.my_ecobee_temperature
            name: Indoor temperature
          - type: tile
            entity: sensor.my_ecobee_humidity
            name: Indoor humidity
      - type: grid
        column_span: 2
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: Scenes
            icon: mdi:creation
          - type: button
            entity: scene.good_morning
            name: Good Morning
            icon: mdi:weather-sunset-up
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.good_morning
          - type: button
            entity: scene.i_m_back
            name: I'm Back
            icon: mdi:home-import-outline
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.i_m_back
          - type: button
            entity: scene.all_lights
            name: All Lights
            icon: mdi:lightbulb-group
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.all_lights
          - type: button
            entity: scene.good_night
            name: Good Night
            icon: mdi:weather-night
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.good_night
          - type: button
            entity: scene.goodbye
            name: Goodbye
            icon: mdi:home-export-outline
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.goodbye
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Lighting
            icon: mdi:lightbulb-group-outline
          - type: tile
            entity: light.main_light
            name: Main
            color: amber
          - type: tile
            entity: light.kitchen_light
            name: Kitchen
            color: amber
          - type: tile
            entity: light.bathroom_light
            name: Bathroom
            color: amber
          - type: tile
            entity: light.doorway_light
            name: Doorway
            color: amber
          - type: tile
            entity: light.bedroom_light
            name: Bedroom
            color: amber
          - type: tile
            entity: light.diningroom_light
            name: Dining Room
            color: amber
          - type: tile
            entity: light.den_light_den_light
            name: Den
            color: amber
          - type: tile
            entity: light.closet_light
            name: Closet
            color: amber
          - type: tile
            entity: light.garage_2
            name: Garage
            color: amber
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: Energy
            icon: mdi:solar-power
          - type: sensor
            entity: sensor.envoy_202308085399_current_power_consumption
            name: Consuming now
            graph: line
            detail: 2
          - type: sensor
            entity: sensor.envoy_202308085399_current_power_production
            name: Solar now
            graph: line
            detail: 2
          - type: tile
            entity: sensor.envoy_202308085399_current_net_power_consumption
            name: Net power
          - type: tile
            entity: sensor.envoy_202308085399_energy_consumption_today
            name: Used today
          - type: tile
            entity: sensor.envoy_202308085399_energy_production_today
            name: Produced today
          - type: history-graph
            title: Power · last 12 hours
            hours_to_show: 12
            entities:
              - entity: sensor.envoy_202308085399_current_power_consumption
                name: Consumption
              - entity: sensor.envoy_202308085399_current_power_production
                name: Production
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Media
            icon: mdi:music-circle-outline
          - type: media-control
            entity: media_player.living_room
          - type: custom:stack-in-card
            cards:
              - type: tile
                entity: script.radio_play
                name: GKR Radio
                icon: mdi:radio
                tap_action:
                  action: perform-action
                  perform_action: script.turn_on
                  target:
                    entity_id: script.radio_play
              - type: tile
                entity: input_number.radio_volume
                name: Radio volume
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: Security & presence
            icon: mdi:shield-home-outline
          - type: custom:button-card
            entity: alarm_control_panel.alarmo
            name: Alarmo
            show_state: true
            state:
              - value: disarmed
                color: '#a7c7a0'
              - value: triggered
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: more-info
              confirmation:
                title: Security
                text: Open alarm controls?
          - type: custom:button-card
            entity: lock.virtual_front_door_lock
            name: Front door
            show_state: true
            state:
              - value: locked
                color: '#a7c7a0'
              - value: unlocked
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: toggle
              confirmation:
                title: Front door
                text: Change the front door lock state?
          - type: custom:button-card
            entity: lock.back_door
            name: Back door
            show_state: true
            state:
              - value: locked
                color: '#a7c7a0'
              - value: unlocked
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: toggle
              confirmation:
                title: Back door
                text: Change the back door lock state?
          - type: tile
            entity: sensor.car_presence
            name: Car
          - type: tile
            entity: person.kcam
            name: Kcam
      - type: grid
        column_span: 2
        background:
          color: '#171a19'
          opacity: 88
        cards:
          - type: heading
            heading: Dashboards
            icon: mdi:view-dashboard-outline
          - type: custom:button-card
            template: luxury_nav
            name: Garage
            icon: mdi:garage
            tap_action:
              action: navigate
              navigation_path: /luxury-garage
          - type: custom:button-card
            template: luxury_nav
            name: Remote
            icon: mdi:remote
            tap_action:
              action: navigate
              navigation_path: /luxury-remote
```

- [ ] **Step 5: Run the Home tests**

Run:

```powershell
python -m unittest tests.test_luxury_home -v
```

Expected: five tests pass.

- [ ] **Step 6: Commit Luxury Home**

```powershell
git add tests/config_assertions.py tests/test_luxury_home.py dashboards/luxury_home.yaml
git commit -m "feat: add responsive Luxury Home dashboard"
```

### Task 3: Build the safe Luxury Garage configuration

**Files:**
- Create: `tests/test_luxury_garage.py`
- Create: `dashboards/luxury_garage.yaml`

- [ ] **Step 1: Write the failing Garage dashboard tests**

Create `tests/test_luxury_garage.py`:

```python
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

    def test_uses_responsive_two_column_sections(self):
        assert_sections_view(self, self.config, max_columns=2)

    def test_references_only_the_approved_garage_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_garage_door_sensor_is_information_only(self):
        cards = cards_for_entity(
            self.config,
            "binary_sensor.lumi_lumi_sensor_magnet_aq2_a84a2103_on_off",
        )
        self.assertTrue(cards)
        for card in cards:
            self.assertEqual(card["tap_action"]["action"], "more-info")
            self.assertNotIn("features", card)

    def test_snapshot_requires_an_explicit_tap(self):
        cards = cards_for_entity(self.config, "script.1645405163026")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["tap_action"]["action"], "perform-action")
        self.assertEqual(
            cards[0]["tap_action"]["perform_action"], "script.turn_on"
        )

    def test_garage_light_uses_the_warm_accent(self):
        cards = cards_for_entity(self.config, "light.garage_2")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["color"], "amber")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the Garage tests and verify the missing file failure**

Run:

```powershell
python -m unittest tests.test_luxury_garage -v
```

Expected: `ERROR` with `FileNotFoundError` for `dashboards/luxury_garage.yaml`.

- [ ] **Step 3: Create the complete Luxury Garage configuration**

Create `dashboards/luxury_garage.yaml`:

```yaml
title: Luxury Garage
button_card_templates:
  luxury_nav:
    show_state: false
    size: 28px
    styles:
      card:
        - border-radius: 18px
        - border: 1px solid rgba(213, 183, 122, 0.24)
        - background: linear-gradient(145deg, rgba(36, 39, 37, 0.96), rgba(18, 20, 20, 0.96))
        - color: '#f6f3ec'
        - padding: 16px
      icon:
        - color: '#d5b77a'
views:
  - title: Garage
    path: garage
    icon: mdi:garage
    type: sections
    max_columns: 2
    dense_section_placement: true
    header:
      layout: responsive
      badges_position: bottom
      card:
        type: markdown
        content: |
          # Luxury Garage
          Door, light, motion, and entry-sensor health at a glance.
        card_mod:
          style: |
            ha-card {
              background: transparent;
              border: 0;
              color: #f6f3ec;
            }
    sections:
      - type: grid
        column_span: 2
        background:
          color: '#1c1a16'
          opacity: 92
        cards:
          - type: heading
            heading: Garage door
            icon: mdi:garage-variant
          - type: custom:button-card
            entity: binary_sensor.lumi_lumi_sensor_magnet_aq2_a84a2103_on_off
            name: Door position
            show_state: true
            state:
              - value: 'off'
                color: '#a7c7a0'
              - value: 'on'
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: more-info
          - type: markdown
            content: |
              **Status only.** No garage-door opener entity is available, so this dashboard never presents an open or close command.
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Controls
            icon: mdi:gesture-tap-button
          - type: tile
            entity: light.garage_2
            name: Garage light
            icon: mdi:lightbulb
            color: amber
          - type: button
            entity: script.1645405163026
            name: Garage Snapshot
            icon: mdi:camera
            tap_action:
              action: perform-action
              perform_action: script.turn_on
              target:
                entity_id: script.1645405163026
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: Sensor health
            icon: mdi:access-point-check
          - type: tile
            entity: binary_sensor.garage_motionsensor
            name: Motion
          - type: tile
            entity: binary_sensor.garage_online
            name: Connection
          - type: tile
            entity: sensor.lumi_lumi_sensor_magnet_aq2_power
            name: Entry sensor battery
          - type: tile
            entity: sensor.lumi_lumi_sensor_magnet_aq2_device_temperature
            name: Entry sensor temperature
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Home climate context
            icon: mdi:home-thermometer-outline
          - type: thermostat
            entity: climate.my_ecobee
            name: Main home
          - type: tile
            entity: sensor.my_ecobee_temperature
            name: Indoor temperature
      - type: grid
        column_span: 2
        background:
          color: '#171a19'
          opacity: 88
        cards:
          - type: heading
            heading: Dashboards
            icon: mdi:view-dashboard-outline
          - type: custom:button-card
            template: luxury_nav
            name: Home
            icon: mdi:home-heart
            tap_action:
              action: navigate
              navigation_path: /luxury-home
          - type: custom:button-card
            template: luxury_nav
            name: Remote
            icon: mdi:remote
            tap_action:
              action: navigate
              navigation_path: /luxury-remote
```

- [ ] **Step 4: Run the Garage tests**

Run:

```powershell
python -m unittest tests.test_luxury_garage -v
```

Expected: five tests pass.

- [ ] **Step 5: Commit Luxury Garage**

```powershell
git add tests/test_luxury_garage.py dashboards/luxury_garage.yaml
git commit -m "feat: add safe Luxury Garage dashboard"
```

### Task 4: Build the phone-first Luxury Remote configuration

**Files:**
- Create: `tests/test_luxury_remote.py`
- Create: `dashboards/luxury_remote.yaml`

- [ ] **Step 1: Write the failing Remote dashboard tests**

Create `tests/test_luxury_remote.py`:

```python
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


class LuxuryRemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT, "dashboards/luxury_remote.yaml")

    def test_uses_single_column_sections_for_phone(self):
        assert_sections_view(self, self.config, max_columns=1)

    def test_references_only_the_approved_remote_entities(self):
        self.assertEqual(referenced_entities(self.config), EXPECTED)

    def test_lock_and_alarm_entry_points_require_confirmation(self):
        for entity_id in (
            "alarm_control_panel.alarmo",
            "lock.virtual_front_door_lock",
            "lock.back_door",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertTrue(cards, entity_id)
            for card in cards:
                self.assertIn("confirmation", card["tap_action"], entity_id)

    def test_camera_shortcuts_only_open_more_info(self):
        for entity_id in (
            "camera.livingroom_2",
            "camera.backyard_backyard_motion_snapshot",
            "camera.blink_backyard",
            "camera.bedroom_bedroom_motion_snapshot",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertEqual(len(cards), 1, entity_id)
            self.assertEqual(cards[0]["tap_action"]["action"], "more-info")

    def test_quick_lights_use_the_warm_accent(self):
        for entity_id in (
            "light.main_light",
            "light.kitchen_light",
            "light.bedroom_light",
            "light.garage_2",
        ):
            cards = cards_for_entity(self.config, entity_id)
            self.assertEqual(len(cards), 1, entity_id)
            self.assertEqual(cards[0]["color"], "amber", entity_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the Remote tests and verify the missing file failure**

Run:

```powershell
python -m unittest tests.test_luxury_remote -v
```

Expected: `ERROR` with `FileNotFoundError` for `dashboards/luxury_remote.yaml`.

- [ ] **Step 3: Create the complete Luxury Remote configuration**

Create `dashboards/luxury_remote.yaml`:

```yaml
title: Luxury Remote
button_card_templates:
  luxury_nav:
    show_state: false
    size: 27px
    styles:
      card:
        - border-radius: 18px
        - border: 1px solid rgba(213, 183, 122, 0.24)
        - background: linear-gradient(145deg, rgba(36, 39, 37, 0.96), rgba(18, 20, 20, 0.96))
        - color: '#f6f3ec'
        - padding: 15px
      icon:
        - color: '#d5b77a'
views:
  - title: Remote
    path: remote
    icon: mdi:remote
    type: sections
    max_columns: 1
    dense_section_placement: true
    header:
      layout: responsive
      badges_position: bottom
      card:
        type: markdown
        content: |
          # Luxury Remote
          The most useful controls, ordered for one-handed access.
        card_mod:
          style: |
            ha-card {
              background: transparent;
              border: 0;
              color: #f6f3ec;
            }
    sections:
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 92
        cards:
          - type: heading
            heading: Security
            icon: mdi:shield-home-outline
          - type: custom:button-card
            entity: alarm_control_panel.alarmo
            name: Alarmo
            show_state: true
            state:
              - value: disarmed
                color: '#a7c7a0'
              - value: triggered
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: more-info
              confirmation:
                title: Security
                text: Open alarm controls?
          - type: custom:button-card
            entity: lock.virtual_front_door_lock
            name: Front door
            show_state: true
            state:
              - value: locked
                color: '#a7c7a0'
              - value: unlocked
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: toggle
              confirmation:
                title: Front door
                text: Change the front door lock state?
          - type: custom:button-card
            entity: lock.back_door
            name: Back door
            show_state: true
            state:
              - value: locked
                color: '#a7c7a0'
              - value: unlocked
                color: '#d88d75'
              - value: unavailable
                color: '#777972'
            tap_action:
              action: toggle
              confirmation:
                title: Back door
                text: Change the back door lock state?
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Quick lights
            icon: mdi:lightbulb-group-outline
          - type: tile
            entity: light.main_light
            name: Main
            color: amber
          - type: tile
            entity: light.kitchen_light
            name: Kitchen
            color: amber
          - type: tile
            entity: light.bedroom_light
            name: Bedroom
            color: amber
          - type: tile
            entity: light.garage_2
            name: Garage
            color: amber
          - type: button
            entity: scene.all_lights
            name: All Lights
            icon: mdi:lightbulb-group
            tap_action:
              action: perform-action
              perform_action: scene.turn_on
              target:
                entity_id: scene.all_lights
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: Comfort
            icon: mdi:home-thermometer-outline
          - type: thermostat
            entity: climate.my_ecobee
            name: Ecobee
          - type: weather-forecast
            entity: weather.home
            forecast_type: daily
            show_forecast: false
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Media
            icon: mdi:music-circle-outline
          - type: media-control
            entity: media_player.living_room
          - type: custom:stack-in-card
            cards:
              - type: tile
                entity: script.radio_play
                name: GKR Radio
                icon: mdi:radio
                tap_action:
                  action: perform-action
                  perform_action: script.turn_on
                  target:
                    entity_id: script.radio_play
              - type: tile
                entity: input_number.radio_volume
                name: Radio volume
      - type: grid
        background:
          color: '#1c1a16'
          opacity: 90
        cards:
          - type: heading
            heading: People & presence
            icon: mdi:account-group-outline
          - type: tile
            entity: person.kcam
            name: Kcam
          - type: tile
            entity: person.mom
            name: Mom
          - type: tile
            entity: binary_sensor.livingroom_matter_pir_occupancy
            name: Living Room occupancy
          - type: tile
            entity: binary_sensor.zachary_s_s21_ultra_presence
            name: Zachary presence
      - type: grid
        background:
          color: '#171a19'
          opacity: 90
        cards:
          - type: heading
            heading: Cameras
            icon: mdi:cctv
          - type: picture-entity
            entity: camera.livingroom_2
            name: Living Room
            camera_view: auto
            show_state: false
            tap_action:
              action: more-info
          - type: picture-entity
            entity: camera.backyard_backyard_motion_snapshot
            name: Backyard snapshot
            camera_view: auto
            show_state: false
            tap_action:
              action: more-info
          - type: picture-entity
            entity: camera.blink_backyard
            name: Blink Backyard
            camera_view: auto
            show_state: false
            tap_action:
              action: more-info
          - type: picture-entity
            entity: camera.bedroom_bedroom_motion_snapshot
            name: Bedroom snapshot
            camera_view: auto
            show_state: false
            tap_action:
              action: more-info
      - type: grid
        background:
          color: '#171a19'
          opacity: 88
        cards:
          - type: heading
            heading: Dashboards
            icon: mdi:view-dashboard-outline
          - type: custom:button-card
            template: luxury_nav
            name: Home
            icon: mdi:home-heart
            tap_action:
              action: navigate
              navigation_path: /luxury-home
          - type: custom:button-card
            template: luxury_nav
            name: Garage
            icon: mdi:garage
            tap_action:
              action: navigate
              navigation_path: /luxury-garage
```

- [ ] **Step 4: Run all configuration tests**

Run:

```powershell
python -m unittest tests.test_dashboard_manifest tests.test_luxury_home tests.test_luxury_garage tests.test_luxury_remote -v
```

Expected: sixteen tests pass.

- [ ] **Step 5: Commit Luxury Remote**

```powershell
git add tests/test_luxury_remote.py dashboards/luxury_remote.yaml
git commit -m "feat: add phone-first Luxury Remote dashboard"
```

### Task 5: Implement the tested Home Assistant deployment client

**Files:**
- Create: `tests/test_deploy_dashboards.py`
- Create: `tools/deploy_dashboards.py`

- [ ] **Step 1: Write deployment, collision, read-back, and rollback tests**

Create `tests/test_deploy_dashboards.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.deploy_dashboards import (
    DeploymentError,
    collect_entity_ids,
    deploy,
    load_entries,
    make_ws_url,
    preflight,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, entries, collision=None, missing_entity=None, fail_save=None):
        self.entries = entries
        self.fail_save = fail_save
        self.deleted = []
        self.configs = {}
        self.dashboards = [
            {
                "id": "existing-overview",
                "url_path": "lovelace",
                "title": "Overview",
                "icon": "mdi:view-dashboard",
                "mode": "storage",
                "show_in_sidebar": True,
                "require_admin": False,
            }
        ]
        if collision:
            self.dashboards.append(
                {
                    "id": "collision",
                    "url_path": collision,
                    "title": "Existing",
                    "mode": "storage",
                    "show_in_sidebar": True,
                    "require_admin": False,
                }
            )
        entity_ids = set()
        for entry in entries:
            entity_ids.update(collect_entity_ids(entry["config_data"]))
        if missing_entity:
            entity_ids.remove(missing_entity)
        self.states = [{"entity_id": entity_id, "state": "off"} for entity_id in entity_ids]

    def command(self, payload):
        command_type = payload["type"]
        if command_type == "lovelace/dashboards/list":
            return [dict(item) for item in self.dashboards]
        if command_type == "get_states":
            return list(self.states)
        if command_type == "lovelace/dashboards/create":
            dashboard = {
                "id": f"created-{payload['url_path']}",
                "url_path": payload["url_path"],
                "title": payload["title"],
                "icon": payload.get("icon"),
                "mode": payload["mode"],
                "show_in_sidebar": payload["show_in_sidebar"],
                "require_admin": payload["require_admin"],
            }
            self.dashboards.append(dashboard)
            return dict(dashboard)
        if command_type == "lovelace/config/save":
            if payload["url_path"] == self.fail_save:
                raise DeploymentError("simulated save failure")
            self.configs[payload["url_path"]] = payload["config"]
            return None
        if command_type == "lovelace/config":
            return self.configs[payload["url_path"]]
        if command_type == "lovelace/dashboards/delete":
            dashboard_id = payload["dashboard_id"]
            self.deleted.append(dashboard_id)
            self.dashboards = [item for item in self.dashboards if item["id"] != dashboard_id]
            return None
        raise AssertionError(f"unexpected command: {payload}")


class DeployDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = load_entries(ROOT, ROOT / "tools" / "dashboard_manifest.yaml")
        cls.resources_ok = lambda _base, _token, _path: True

    def test_websocket_url_conversion(self):
        self.assertEqual(
            make_ws_url("https://example.duckdns.org:8123"),
            "wss://example.duckdns.org:8123/api/websocket",
        )
        self.assertEqual(
            make_ws_url("http://192.168.1.10:8123/"),
            "ws://192.168.1.10:8123/api/websocket",
        )

    def test_preflight_rejects_path_collision(self):
        client = FakeClient(self.entries, collision="luxury-home")
        with self.assertRaisesRegex(DeploymentError, "already exist"):
            preflight(client, "https://ha.example", "secret", self.entries, self.resources_ok)

    def test_preflight_rejects_missing_entity(self):
        client = FakeClient(self.entries, missing_entity="light.garage_2")
        with self.assertRaisesRegex(DeploymentError, "light.garage_2"):
            preflight(client, "https://ha.example", "secret", self.entries, self.resources_ok)

    def test_preflight_rejects_missing_frontend_resource(self):
        client = FakeClient(self.entries)
        checker = lambda _base, _token, path: "stack-in-card" not in path
        with self.assertRaisesRegex(DeploymentError, "stack-in-card"):
            preflight(client, "https://ha.example", "secret", self.entries, checker)

    def test_apply_creates_saves_and_reads_back_all_three(self):
        client = FakeClient(self.entries)
        report = preflight(
            client, "https://ha.example", "secret", self.entries, self.resources_ok
        )
        with TemporaryDirectory() as temporary:
            result = deploy(client, self.entries, report, Path(temporary))
        self.assertEqual(result["status"], "deployed")
        self.assertEqual(
            [item["url_path"] for item in result["created"]],
            ["luxury-home", "luxury-garage", "luxury-remote"],
        )
        self.assertEqual(set(client.configs), {"luxury-home", "luxury-garage", "luxury-remote"})
        self.assertEqual(client.deleted, [])

    def test_save_failure_rolls_back_only_dashboards_from_current_run(self):
        client = FakeClient(self.entries, fail_save="luxury-garage")
        report = preflight(
            client, "https://ha.example", "secret", self.entries, self.resources_ok
        )
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(DeploymentError, "simulated save failure"):
                deploy(client, self.entries, report, Path(temporary))
        self.assertEqual(
            client.deleted,
            ["created-luxury-garage", "created-luxury-home"],
        )
        self.assertEqual([item["id"] for item in client.dashboards], ["existing-overview"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the deployment tests and verify the missing module failure**

Run:

```powershell
python -m unittest tests.test_deploy_dashboards -v
```

Expected: `ERROR` with `ModuleNotFoundError` for `tools.deploy_dashboards`.

- [ ] **Step 3: Implement the complete deployment client**

Create `tools/deploy_dashboards.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import websocket
import yaml


ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
REQUIRED_RESOURCES = (
    "/hacsfiles/button-card/button-card.js",
    "/hacsfiles/lovelace-card-mod/card-mod.js",
    "/hacsfiles/stack-in-card/stack-in-card.js",
)


class DeploymentError(RuntimeError):
    pass


def make_ws_url(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DeploymentError(f"invalid Home Assistant URL: {base_url}")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))


def load_entries(root: Path, manifest_path: Path) -> list[dict]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entries = []
    for raw in manifest["dashboards"]:
        entry = dict(raw)
        config_path = root / entry["config"]
        entry["config_data"] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        entries.append(entry)
    return entries


def collect_entity_ids(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"entity", "entity_id"}:
                candidates = child if isinstance(child, list) else [child]
                for candidate in candidates:
                    if isinstance(candidate, str) and ENTITY_ID.fullmatch(candidate):
                        found.add(candidate)
            found.update(collect_entity_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(collect_entity_ids(child))
    return found


class HomeAssistantWebSocket:
    def __init__(self, base_url: str, token: str, timeout: int = 20):
        self.url = make_ws_url(base_url)
        self.token = token
        self.timeout = timeout
        self.socket = None
        self.next_id = 1

    def __enter__(self):
        self.socket = websocket.create_connection(self.url, timeout=self.timeout)
        required = self._receive()
        if required.get("type") != "auth_required":
            raise DeploymentError(f"expected auth_required, got {required}")
        self.socket.send(json.dumps({"type": "auth", "access_token": self.token}))
        authenticated = self._receive()
        if authenticated.get("type") != "auth_ok":
            raise DeploymentError(f"Home Assistant authentication failed: {authenticated}")
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.socket is not None:
            self.socket.close()

    def _receive(self) -> dict:
        return json.loads(self.socket.recv())

    def command(self, payload: dict):
        request_id = self.next_id
        self.next_id += 1
        message = dict(payload)
        message["id"] = request_id
        self.socket.send(json.dumps(message))
        while True:
            response = self._receive()
            if response.get("id") != request_id:
                continue
            if response.get("type") != "result":
                raise DeploymentError(f"unexpected WebSocket response: {response}")
            if not response.get("success"):
                error = response.get("error", {})
                raise DeploymentError(
                    f"{payload['type']} failed: {error.get('code', 'unknown')}: "
                    f"{error.get('message', error)}"
                )
            return response.get("result")


def http_resource_status(base_url: str, token: str, resource_path: str) -> bool:
    request = Request(
        f"{base_url.rstrip('/')}{resource_path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return 200 <= response.status < 400
    except HTTPError as error:
        return 200 <= error.code < 400
    except URLError as error:
        raise DeploymentError(f"resource preflight failed for {resource_path}: {error}") from error


def preflight(client, base_url, token, entries, resource_checker=http_resource_status):
    original_dashboards = client.command({"type": "lovelace/dashboards/list"})
    requested_paths = {entry["url_path"] for entry in entries}
    collisions = sorted(
        item["url_path"]
        for item in original_dashboards
        if item.get("url_path") in requested_paths
    )
    if collisions:
        raise DeploymentError(f"dashboard paths already exist: {', '.join(collisions)}")

    states = client.command({"type": "get_states"})
    live_entities = {item["entity_id"] for item in states}
    required_entities = set()
    for entry in entries:
        required_entities.update(collect_entity_ids(entry["config_data"]))
    missing_entities = sorted(required_entities - live_entities)
    if missing_entities:
        raise DeploymentError(f"missing live entities: {', '.join(missing_entities)}")

    missing_resources = [
        path
        for path in REQUIRED_RESOURCES
        if not resource_checker(base_url, token, path)
    ]
    if missing_resources:
        raise DeploymentError(f"missing frontend resources: {', '.join(missing_resources)}")

    return {
        "status": "ready",
        "original_dashboards": original_dashboards,
        "target_paths": [entry["url_path"] for entry in entries],
        "verified_entities": sorted(required_entities),
        "verified_resources": list(REQUIRED_RESOURCES),
    }


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def deploy(client, entries, preflight_report, artifact_dir: Path):
    write_json(artifact_dir / "pre-deploy-dashboard-registry.json", preflight_report)
    original_by_id = {
        item["id"]: item for item in preflight_report["original_dashboards"]
    }
    created = []
    try:
        for entry in entries:
            dashboard = client.command(
                {
                    "type": "lovelace/dashboards/create",
                    "url_path": entry["url_path"],
                    "title": entry["title"],
                    "icon": entry["icon"],
                    "mode": entry["mode"],
                    "show_in_sidebar": entry["show_in_sidebar"],
                    "require_admin": entry["require_admin"],
                }
            )
            created.append(dashboard)
            client.command(
                {
                    "type": "lovelace/config/save",
                    "url_path": entry["url_path"],
                    "config": entry["config_data"],
                }
            )
            saved = client.command(
                {
                    "type": "lovelace/config",
                    "url_path": entry["url_path"],
                    "force": True,
                }
            )
            if saved != entry["config_data"]:
                raise DeploymentError(f"read-back mismatch for {entry['url_path']}")

        final_dashboards = client.command({"type": "lovelace/dashboards/list"})
        final_by_id = {item["id"]: item for item in final_dashboards}
        for dashboard_id, original in original_by_id.items():
            if final_by_id.get(dashboard_id) != original:
                raise DeploymentError(f"existing dashboard changed: {dashboard_id}")

        result = {
            "status": "deployed",
            "created": created,
            "final_dashboards": final_dashboards,
        }
        write_json(artifact_dir / "deployment-result.json", result)
        return result
    except Exception as error:
        rollback_errors = []
        for dashboard in reversed(created):
            try:
                client.command(
                    {
                        "type": "lovelace/dashboards/delete",
                        "dashboard_id": dashboard["id"],
                    }
                )
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        failure = {
            "status": "rolled_back" if not rollback_errors else "rollback_incomplete",
            "error": str(error),
            "deleted_dashboard_ids": [item["id"] for item in reversed(created)],
            "rollback_errors": rollback_errors,
        }
        write_json(artifact_dir / "deployment-failure.json", failure)
        if rollback_errors:
            raise DeploymentError(
                f"{error}; rollback errors: {'; '.join(rollback_errors)}"
            ) from error
        raise DeploymentError(str(error)) from error


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Deploy additive Luxury Lovelace dashboards")
    parser.add_argument("--base-url", default=os.environ.get("HA_URL"))
    parser.add_argument("--token-env", default="HA_TOKEN")
    parser.add_argument("--manifest", default="tools/dashboard_manifest.yaml")
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    token = os.environ.get(args.token_env)
    if not args.base_url:
        print("HA_URL or --base-url is required", file=sys.stderr)
        return 2
    if not token:
        print(f"{args.token_env} must contain a process-scoped token", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parents[1]
    entries = load_entries(root, root / args.manifest)
    artifact_dir = root / args.artifact_dir
    try:
        with HomeAssistantWebSocket(args.base_url, token) as client:
            report = preflight(client, args.base_url, token, entries)
            write_json(artifact_dir / "preflight.json", report)
            if not args.apply:
                print(json.dumps({"status": "dry-run", **report}, indent=2))
                return 0
            result = deploy(client, entries, report, artifact_dir)
            print(json.dumps(result, indent=2))
            return 0
    except DeploymentError as error:
        print(f"deployment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the deployment tests**

Run:

```powershell
python -m unittest tests.test_deploy_dashboards -v
```

Expected: six tests pass, including rejection of a missing resource and rollback of only the two dashboards created before the simulated failure.

- [ ] **Step 5: Run the full local suite and syntax checks**

Run:

```powershell
python -m unittest discover -s tests -v
python -m py_compile tools/deploy_dashboards.py
git diff --check
```

Expected: twenty-two tests pass; compilation and diff checks exit zero.

- [ ] **Step 6: Commit the deployment client**

```powershell
git add tools/deploy_dashboards.py tests/test_deploy_dashboards.py
git commit -m "feat: add atomic Home Assistant dashboard deployer"
```

### Task 6: Document the safe operator workflow

**Files:**
- Create: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Exclude local deployment evidence**

Create `.gitignore`:

```gitignore
# Local Home Assistant deployment evidence; never commit instance metadata.
artifacts/
```

- [ ] **Step 2: Append exact deployment instructions to the README**

Append this section to `README.md`:

````markdown

## Responsive Luxury dashboards

This fork adds three storage-mode dashboards that are mapped to one Home Assistant instance:

- Luxury Home: `/luxury-home/home`
- Luxury Garage: `/luxury-garage/garage`
- Luxury Remote: `/luxury-remote/remote`

The deployer is additive. It stops if any target URL path already exists, validates all referenced entities and required HACS resources, reads every saved configuration back, and removes only dashboards created by a failed run.

### Local validation

```powershell
python -m pip install -r requirements-dashboard.txt
python -m unittest discover -s tests -v
```

### Credential-safe preflight

Set the Home Assistant URL and a process-scoped token without writing the token to a file:

```powershell
$env:HA_URL = 'https://kcam-hassio.duckdns.org:8123'
$secureToken = Read-Host 'Temporary Home Assistant token' -AsSecureString
$env:HA_TOKEN = [System.Net.NetworkCredential]::new('', $secureToken).Password
python tools/deploy_dashboards.py
```

A successful dry-run prints `"status": "dry-run"` and writes credential-free evidence under `artifacts/`.

### Deploy

```powershell
python tools/deploy_dashboards.py --apply
Remove-Item Env:HA_TOKEN
Remove-Variable secureToken
```

After verification, revoke the temporary Home Assistant token from the Home Assistant profile.

### Rollback after a successful deployment

Use **Settings → Dashboards** to delete only Luxury Home, Luxury Garage, and Luxury Remote. A failed deployment rolls back those newly created dashboards automatically.
````

- [ ] **Step 3: Verify documentation commands and repository hygiene**

Run:

```powershell
python tools/deploy_dashboards.py --help
python -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: help exits zero; twenty-two tests pass; diff check exits zero; only `.gitignore` and `README.md` are pending.

- [ ] **Step 4: Commit the operator workflow**

```powershell
git add .gitignore README.md
git commit -m "docs: add safe dashboard deployment workflow"
```

### Task 7: Run a live read-only preflight

**Files:**
- Runtime output only: `artifacts/preflight.json`

- [ ] **Step 1: Confirm the repository is clean and tests still pass**

Run:

```powershell
git status --short
python -m unittest discover -s tests -v
```

Expected: Git status is empty and twenty-two tests pass.

- [ ] **Step 2: Supply the Home Assistant credential only to the current process**

Use the already available process-scoped credential if execution inherited one. Otherwise use the secure prompt shown in the README. Do not paste a token into a committed file, command-line argument, dashboard configuration, test fixture, or deployment artifact.

Set the endpoint:

```powershell
$env:HA_URL = 'https://kcam-hassio.duckdns.org:8123'
```

- [ ] **Step 3: Execute the dry-run preflight**

Run:

```powershell
python tools/deploy_dashboards.py
```

Expected output contains:

```json
{
  "status": "dry-run",
  "target_paths": [
    "luxury-home",
    "luxury-garage",
    "luxury-remote"
  ]
}
```

The full output must also show all referenced entities verified, the three required HACS resources verified, and no target-path collisions. Any collision, missing entity, authentication error, or missing resource stops execution with no Home Assistant mutations.

- [ ] **Step 4: Inspect the credential-free preflight artifact**

Run:

```powershell
$report = Get-Content -Raw artifacts\preflight.json | ConvertFrom-Json
$report.status
$report.target_paths
$report.verified_resources
Select-String -Path artifacts\preflight.json -Pattern 'access_token|HA_TOKEN|Bearer'
```

Expected: status is `ready`; the three target paths and required resources are present; the credential scan returns no matches.

### Task 8: Deploy and verify the three live dashboards

**Files:**
- Runtime output only: `artifacts/pre-deploy-dashboard-registry.json`
- Runtime output only: `artifacts/deployment-result.json`

- [ ] **Step 1: Apply the preflighted configurations**

Run:

```powershell
python tools/deploy_dashboards.py --apply
```

Expected: output status is `deployed`; the created paths are `luxury-home`, `luxury-garage`, and `luxury-remote`. The command reads all three configurations back and verifies every original dashboard registry record is unchanged before returning success.

- [ ] **Step 2: Validate the deployment artifact contains no credential**

Run:

```powershell
$result = Get-Content -Raw artifacts\deployment-result.json | ConvertFrom-Json
$result.status
$result.created | Select-Object title,url_path,id
Select-String -Path artifacts\*.json -Pattern 'access_token|HA_TOKEN|Bearer'
```

Expected: status is `deployed`; exactly three created dashboards are listed; the credential scan returns no matches.

- [ ] **Step 3: Open each live dashboard and inspect the rendered result**

Use the in-app browser with the authenticated Home Assistant session and open:

```text
https://kcam-hassio.duckdns.org:8123/luxury-home/home
https://kcam-hassio.duckdns.org:8123/luxury-garage/garage
https://kcam-hassio.duckdns.org:8123/luxury-remote/remote
```

At each URL, verify all of the following:

- The page renders without an invalid-configuration card or missing custom-element message.
- Live entity values appear instead of repository placeholders.
- Unavailable devices remain visible and clearly unavailable.
- Home, Garage, and Remote navigation reaches the intended dashboard.
- The Garage door is shown as status-only and has no open/close command.
- Camera taps open more-info and do not trigger recording.
- Garage Snapshot is not triggered during verification.

- [ ] **Step 4: Verify confirmation behavior without changing security state**

Tap the Alarmo, Front door, and Back door cards. Confirm that each displays the configured confirmation dialog. Dismiss every dialog; do not confirm any alarm or lock operation.

Expected: all three security entry points show confirmation, and their underlying states remain unchanged.

- [ ] **Step 5: Verify responsive behavior at three viewport widths**

Inspect each dashboard at these representative widths:

```text
390 × 844   phone
768 × 1024  tablet
1280 × 800  desktop
```

Expected: no horizontal scrolling; touch controls do not overlap; Remote remains a single content column; Home and Garage expand to at most two sections across; primary controls remain ahead of secondary detail.

- [ ] **Step 6: Check browser console and final repository state**

Inspect the browser console on all three dashboards.

Expected: no errors naming `button-card`, `card-mod`, `stack-in-card`, unknown card types, or invalid entity IDs.

Then run:

```powershell
git status --short
Remove-Item Env:HA_TOKEN -ErrorAction SilentlyContinue
Remove-Variable secureToken -ErrorAction SilentlyContinue
```

Expected: Git status is clean because `artifacts/` is ignored, and the process-scoped token is removed.

- [ ] **Step 7: Hand off the live URLs and token-revocation action**

Report the three verified dashboard URLs and explicitly instruct the user to revoke the temporary token from the Home Assistant profile. Do not repeat the token in the handoff.

## Reference contracts

- Home Assistant WebSocket authentication and command envelope: <https://developers.home-assistant.io/docs/api/websocket/>
- Home Assistant frontend dashboard create/list/update/delete message shapes: <https://github.com/home-assistant/frontend/blob/dev/src/data/lovelace/dashboard.ts>
- Home Assistant frontend Lovelace config read/save/delete message shapes: <https://github.com/home-assistant/frontend/blob/dev/src/data/lovelace/config/types.ts>
- Sections view responsive configuration: <https://www.home-assistant.io/dashboards/sections/>
- Dashboard confirmation actions: <https://www.home-assistant.io/dashboards/actions/#confirmation>
- Clock card configuration: <https://www.home-assistant.io/dashboards/clock/>
