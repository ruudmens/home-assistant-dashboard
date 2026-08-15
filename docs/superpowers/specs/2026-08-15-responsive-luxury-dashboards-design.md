# Responsive Luxury Home Assistant Dashboards

**Status:** Approved design

**Date:** 2026-08-15

**Source inspiration:** [ruudmens/home-assistant-dashboard](https://github.com/ruudmens/home-assistant-dashboard)

## Objective

Create three new responsive Home Assistant dashboards inspired by the source repository, but mapped to the live entities currently available in the user's Home Assistant instance. Preserve all existing dashboards and avoid introducing broken cards for entity types or frontend dependencies that are not available.

## Approved dashboard names and paths

| Dashboard | URL path | Primary use |
| --- | --- | --- |
| Luxury Home | `/luxury-home` | Whole-home wall tablet and desktop dashboard |
| Luxury Garage | `/luxury-garage` | Garage status and controls |
| Luxury Remote | `/luxury-remote` | Compact phone-first remote |

These are additive storage-mode dashboards. No existing dashboard will be renamed, replaced, or edited.

## Design direction

Use a responsive, source-inspired adaptation rather than an exact fixed-size clone. The visual language is dark and restrained, with warm neutral accents, clear state colors, rounded panels, consistent spacing, and large touch targets.

- At widths of approximately 960 px and above, content flows into two columns.
- Tablet widths use the same hierarchy with fewer columns where required.
- Phone widths collapse to a single vertical flow without horizontal scrolling.
- Essential information and high-frequency controls appear before secondary detail.
- Garage and Remote reuse the same card styling, spacing, navigation, and state semantics as Home.

## Frontend component strategy

Use the already available custom components where they materially improve the result:

- `custom:button-card`
- `custom:layout-card`
- `card-mod`
- `custom:stack-in-card`

Do not depend on `price-timeline-card` or `kiosk-mode`, because their frontend resources are not currently installed. Use native Home Assistant history, statistic, gauge, tile, entities, weather, media-control, thermostat, and picture-entity cards where they are the more reliable fit.

The first release will not install new HACS integrations, create helpers, add automations, or modify the Home Assistant theme globally.

## Dashboard content

### Luxury Home

The Home dashboard is the primary overview and follows this order:

1. Header with time/date, weather, Ecobee temperature, and humidity.
2. Scene row for Good Morning, I'm Back, All Lights, Good Night, and Goodbye.
3. Responsive room-light grid.
4. Energy consumption and solar-production overview.
5. Living Room media and GKR radio controls.
6. Alarm, locks, door state, presence, and parked-car summary.
7. Navigation to Garage and Remote.

Primary mappings:

| Function | Entity |
| --- | --- |
| Weather | `weather.home` |
| Thermostat | `climate.my_ecobee` |
| Temperature | `sensor.my_ecobee_temperature` |
| Humidity | `sensor.my_ecobee_humidity` |
| Good Morning | `scene.good_morning` |
| I'm Back | `scene.i_m_back` |
| All Lights | `scene.all_lights` |
| Good Night | `scene.good_night` |
| Goodbye | `scene.goodbye` |
| Main light | `light.main_light` |
| Kitchen | `light.kitchen_light` |
| Bathroom | `light.bathroom_light` |
| Doorway | `light.doorway_light` |
| Bedroom | `light.bedroom_light` |
| Dining room | `light.diningroom_light` |
| Den | `light.den_light_den_light` |
| Closet | `light.closet_light` |
| Garage | `light.garage_2` |
| Current consumption | `sensor.envoy_202308085399_current_power_consumption` |
| Current production | `sensor.envoy_202308085399_current_power_production` |
| Net consumption | `sensor.envoy_202308085399_current_net_power_consumption` |
| Consumption today | `sensor.envoy_202308085399_energy_consumption_today` |
| Production today | `sensor.envoy_202308085399_energy_production_today` |
| Living Room media | `media_player.living_room` |
| GKR radio action | `script.radio_play` |
| Radio volume | `input_number.radio_volume` |
| Alarm | `alarm_control_panel.alarmo` |
| Front lock | `lock.virtual_front_door_lock` |
| Back lock | `lock.back_door` |
| Car presence | `sensor.car_presence` |
| Primary person | `person.kcam` |

The source dashboard's detailed vehicle metrics are replaced with the available parked-car status. Its price timeline is replaced by native current-energy and historical-energy cards.

### Luxury Garage

The Garage dashboard is intentionally focused rather than reproducing an unavailable garage thermostat or camera.

1. Garage-door state as the dominant status.
2. Garage light toggle.
3. Motion, connectivity, sensor battery, and device-temperature status.
4. Explicit Garage Snapshot action.
5. Compact home climate summary for environmental context.
6. Navigation to Home and Remote.

Primary mappings:

| Function | Entity |
| --- | --- |
| Garage light | `light.garage_2` |
| Garage door sensor | `binary_sensor.lumi_lumi_sensor_magnet_aq2_a84a2103_on_off` |
| Garage motion | `binary_sensor.garage_motionsensor` |
| Garage online status | `binary_sensor.garage_online` |
| Entry sensor battery | `sensor.lumi_lumi_sensor_magnet_aq2_power` |
| Entry sensor temperature | `sensor.lumi_lumi_sensor_magnet_aq2_device_temperature` |
| Snapshot action | `script.1645405163026` |
| Home climate context | `climate.my_ecobee` |

The door sensor is informational only. No garage-door opener entity was found, so the design must not imply that the door can be opened or closed from this dashboard.

### Luxury Remote

The Remote dashboard is phone-first and optimized for common actions:

1. Alarm and lock controls.
2. Common room lights and All Lights scene.
3. Ecobee climate and weather.
4. Living Room media, GKR radio, and volume.
5. People and presence status.
6. Camera shortcuts.
7. Navigation to Home and Garage.

Primary camera shortcuts may include:

- `camera.livingroom_2`
- `camera.backyard_backyard_motion_snapshot`
- `camera.blink_backyard`
- `camera.bedroom_bedroom_motion_snapshot`

The source dashboard's irrigation controls are omitted because no matching live irrigation entities were found.

## State and interaction behavior

- Cards read current Home Assistant entity state and update through normal Lovelace state subscriptions.
- Unavailable entities remain visible in their intended location, are visually muted, and display an unavailable state rather than disappearing and shifting the layout.
- Lock and alarm actions require confirmation.
- Lights, scenes, media actions, and volume controls remain direct one-tap interactions.
- Garage Snapshot runs only from an explicit user tap.
- Camera cards open the selected Home Assistant camera view; they do not trigger recording or other side effects.
- Navigation between the three dashboards uses fixed dashboard URL paths.
- State color is meaningful and consistent: warm accent for active lights/scenes, green for secure/normal states, and warning color for open, unlocked, offline, or triggered states.

## Delivery architecture

Create the dashboards through Home Assistant's authenticated WebSocket/Lovelace APIs as new storage-mode dashboard records, then save each dashboard configuration under its assigned URL path.

Before mutation:

1. Read the current Lovelace dashboard registry.
2. Confirm the three target URL paths are unused.
3. Refresh the live entity inventory.
4. Confirm required frontend resources still load.
5. Capture the original dashboard registry for comparison and rollback evidence.

If a target path unexpectedly exists, stop rather than overwrite it.

Authentication credentials must remain ephemeral. They must not be written to the repository, dashboard YAML, scripts, logs, or specification. Prefer the configured Home Assistant MCP connection when available; otherwise use a process-scoped credential solely for the API session.

## Validation

Validation must cover both configuration state and rendered behavior:

1. Confirm every referenced entity exists immediately before saving.
2. Confirm every required custom frontend resource returns successfully.
3. Create each dashboard and require a successful API response.
4. Read back the dashboard registry and all three saved Lovelace configurations.
5. Verify the original dashboard registry entries remain present and unchanged.
6. Open each dashboard in Home Assistant and check for missing custom elements, invalid configuration warnings, or unavailable references caused by misspelled entity IDs.
7. Exercise non-destructive controls such as navigation and card expansion.
8. Verify confirmation dialogs for alarm and lock actions without completing a state-changing command during validation.
9. Inspect Home, Garage, and Remote at representative phone, tablet, and desktop widths.
10. Confirm touch targets, card order, wrapping, and the absence of horizontal scrolling.

Sample energy numbers in the visual mockup are illustrative; the implemented cards must display live entity values.

## Rollback

Rollback is limited to deleting the three newly created dashboard records and their configurations. Because the design is additive and does not modify global themes, automations, helpers, HACS resources, or existing dashboards, rollback does not require restoring unrelated Home Assistant configuration.

## Acceptance criteria

- `/luxury-home`, `/luxury-garage`, and `/luxury-remote` load successfully.
- Each dashboard uses current live entities and contains no source-repository placeholders.
- Existing dashboards remain intact.
- No missing-card or invalid-entity configuration errors appear.
- Lock and alarm actions require confirmation.
- Garage door state is not presented as a controllable opener.
- Layouts are usable without horizontal scrolling on phone, tablet, and desktop widths.
- The result retains the source dashboard's premium dark visual character while adapting responsibly to the available Home Assistant capabilities.
