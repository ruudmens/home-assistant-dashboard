# Luxury Cameras Dashboard Design

**Date:** 2026-08-16  
**Status:** Approved design, awaiting written-spec review

## Purpose

Add one responsive, storage-mode Home Assistant dashboard that presents every camera from the already configured Scrypted NVR without modifying or recreating the existing Luxury Home, Luxury Garage, or Luxury Remote dashboards.

The final dashboard URL will be:

`/luxury-cameras/cameras`

## Confirmed live prerequisites

- The Home Assistant Scrypted custom component is loaded.
- The configured Scrypted integration resolves both known LAN interfaces to the same server.
- Scrypted NVR is licensed.
- The Scrypted NVR JavaScript and CSS Lovelace resources return successfully through the Home Assistant proxy.
- The live Scrypted inventory contains 17 camera devices.

No Home Assistant token, Scrypted token, username, password, proxy URL containing a token, or generated authorization value may be written to source files, artifacts, logs, tests, or documentation.

## Dashboard identity

| Field | Value |
|---|---|
| Title | Luxury Cameras |
| Dashboard path | `luxury-cameras` |
| View path | `cameras` |
| Icon | `mdi:cctv` |
| Mode | storage |
| Sidebar | visible |
| Admin-only | no |

Deployment uses a camera-only manifest. This prevents the additive deployer from treating the three existing Luxury dashboard paths as collisions or attempting to recreate them.

## Visual system

The dashboard extends the approved Luxury visual language:

- near-black navy background;
- translucent blue-black cards;
- restrained cyan and violet accents;
- soft borders, rounded corners, and minimal shadows;
- compact typography and controls;
- no decorative imagery that competes with camera footage.

The navigation footer links back to:

- `/luxury-home/home`
- `/luxury-garage/garage`
- `/luxury-remote/remote`

The three existing dashboards remain unchanged. The Home Assistant sidebar provides entry into Luxury Cameras.

## Responsive layout

The single Sections view uses four functional areas.

### Header

The header contains the dashboard title, a concise "17 cameras" status label, and an unobtrusive Scrypted NVR indicator. It contains no token sensor, credential value, raw host address, or configuration action.

### Primary live grid

Four primary cameras autoplay at the Scrypted `low-resolution` destination:

| Scrypted card ID | Display name |
|---|---|
| `107` | Front Door |
| `266` | Back Yard |
| `124` | Bedroom |
| `268` | Living Room |

Each uses `custom:scrypted-nvr-camera` with:

- `live: true`;
- `destination: low-resolution`;
- `imageClick: popup`;
- `videoClick: popup`;
- dark theme and a 16:9 presentation;
- microphone and speaker left off.

The grid is four columns on wide desktop displays, two columns on tablets, and one column on phones.

### Remaining camera grid

The remaining 13 Scrypted cameras appear as non-autoplay click-to-play cards:

| Scrypted card ID | Display name |
|---|---|
| `267` | Back Yard 2 |
| `287` | Blink Backyard |
| `286` | Blink Backyard 2 |
| `289` | GNT2 Camera |
| `288` | Living Room 2 |
| `290` | Mini Camera |
| `269` | OG Camera |
| `250` | RTSP Camera A |
| `264` | RTSP Camera B |
| `171` | Tapo C211 A |
| `173` | Tapo C211 B |
| `270` | U1 |
| `271` | V4 |

These cards use the same low-resolution destination but omit `live: true`. Clicking opens the Scrypted popup. Raw RTSP URLs and private host addresses are not displayed.

The remaining grid is four columns on wide desktop displays, two columns on tablets, and one column on phones.

### Recent event reel

A full-width `custom:scrypted-nvr-events-carousel` shows recent events across all cameras. Camera IDs are intentionally omitted so the Scrypted component supplies the complete live inventory. Motion-only events remain hidden by the card default, while classified detections remain visible. Clicking an event opens the Home Assistant-integrated Scrypted view.

## Safety and performance

- Only four low-resolution streams autoplay.
- The other 13 cameras load as non-autoplay cards.
- No card enables the microphone or speaker automatically.
- No camera service calls, snapshots, recording changes, PTZ commands, lock actions, alarm actions, or automation triggers are present.
- Camera and event clicks are limited to safe Scrypted popup or Home Assistant navigation behavior.
- The dashboard never embeds a direct RTSP URL or Scrypted credential.
- Existing dashboards and their stored configurations are preserved byte-for-byte by deployment verification.

## Source changes

Implementation will add:

- `dashboards/luxury_cameras.yaml`
- `tools/scrypted_dashboard_manifest.yaml`
- `tests/test_luxury_cameras.py`
- focused manifest/resource-preflight tests as required

The deployer may be extended only as needed to validate token-bearing Scrypted resources safely by their non-secret URL suffix and declared resource type. Dynamic proxy URLs must remain process-scoped and must be sanitized from artifacts and errors.

## Validation contract

### Automated tests

Tests will verify:

- dashboard and view identity;
- exact primary and secondary Scrypted card IDs;
- four autoplay cards and 13 non-autoplay cards;
- low-resolution destination on all camera cards;
- microphone and speaker are not enabled;
- the all-camera event reel is present without an ID filter;
- responsive four/two/one-column behavior;
- navigation paths;
- absence of service actions, direct stream URLs, credentials, token-shaped strings, and private host addresses;
- camera-only manifest isolation;
- safe Scrypted resource discovery and sanitization.

### Live preflight

Before apply, the operator will:

1. confirm the Scrypted config entry is loaded;
2. confirm the NVR module and CSS resources are registered and return HTTP 200;
3. use a process-scoped official Scrypted client connection to compare the 17 configured card IDs with the current Camera inventory and confirm the NVR license;
4. confirm `luxury-cameras` has no dashboard or panel collision;
5. scan all generated evidence silently for credential markers, token values, and authorization values.

Temporary client connection logs must be suppressed because the official client can log generated authorization data. Tokens and generated authorizations are cleared immediately after the check.

### Apply and verification

The apply operation creates only `luxury-cameras`, saves its configuration, reads it back for exact equality, and verifies every pre-existing dashboard registry record remains unchanged.

After apply, browser verification covers desktop, tablet, and phone widths and checks:

- all custom cards render without configuration errors;
- exactly four primary cards autoplay;
- remaining cards do not autoplay;
- the event reel renders;
- navigation links resolve correctly;
- no confirmation dialog or control can trigger a camera-side action;
- the final URL is `/luxury-cameras/cameras`.

## Failure behavior

- Missing or duplicate Scrypted resources block apply.
- An unlicensed NVR, missing camera ID, dashboard collision, panel collision, invalid configuration, failed read-back, or changed original registry blocks completion.
- If creation begins and later fails, rollback follows the existing ownership-safe reverse-delete behavior.
- Ambiguous creation outcomes that cannot be reconciled remain `rollback_incomplete` and require manual review.
- Manual cleanup targets the exact `luxury-cameras` URL path, never a title match.
