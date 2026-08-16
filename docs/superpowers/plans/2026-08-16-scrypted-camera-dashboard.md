# Luxury Cameras Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a responsive, dark Luxury Cameras Home Assistant dashboard containing all 17 Scrypted cameras, with four low-resolution autoplay feeds, thirteen click-to-play feeds, and an all-camera NVR event reel at `/luxury-cameras/cameras`.

**Architecture:** Keep the existing three-dashboard manifest and deployed dashboards untouched. Add one camera-only manifest, extend the current transactional deployer with optional credential-safe frontend-resource discovery, and describe the camera dashboard as tested Lovelace YAML. The deployer will resolve registered Scrypted resources only at runtime, validate that they are relative same-origin URLs, use any dynamic tokenized URL only in memory for the HTTP check, and persist only sanitized suffix requirements.

**Tech Stack:** Python 3 standard library, PyYAML, websocket-client, `unittest`, Home Assistant Lovelace storage WebSocket API, `layout-card`, `button-card`, and the official Scrypted NVR web components.

---

## Task 1: Add optional safe Lovelace-resource requirements to the deployer

**Files:**
- Modify: `tools/deploy_dashboards.py`
- Modify: `tests/test_deploy_dashboards.py`

- [ ] **Step 1: Write failing manifest-loader tests**

Add tests proving that `load_manifest(root, manifest_path)` returns both `entries` and validated `resource_requirements`, while the public compatibility wrapper `load_entries(...)` still returns the same ordered three entries from `tools/dashboard_manifest.yaml`.

Use a temporary manifest containing:

```yaml
resource_requirements:
  - type: module
    url_suffix: /endpoint/@scrypted/nvr/assets/web-components.js
  - type: css
    url_suffix: /endpoint/@scrypted/nvr/assets/web-components.css
dashboards:
  - url_path: luxury-test
    title: Luxury Test
    icon: mdi:cctv
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/test.yaml
```

Assert rejection with the existing generic, secret-safe loader error for:

```python
invalid_requirements = [
    "not-a-list",
    ["not-a-mapping"],
    [{"type": "javascript", "url_suffix": "/safe.js"}],
    [{"type": "module", "url_suffix": "relative.js"}],
    [{"type": "module", "url_suffix": "https://evil.example/x.js"}],
    [{"type": "module", "url_suffix": "//evil.example/x.js"}],
    [{"type": "module", "url_suffix": "/x.js?token=secret"}],
    [{"type": "module", "url_suffix": "/x.js#fragment"}],
]
```

Also reject duplicate `(type, url_suffix)` pairs. Confirm an absent `resource_requirements` key becomes an empty list so the original manifest behavior does not change.

- [ ] **Step 2: Run the focused loader tests and observe failure**

Run:

```powershell
python -m unittest tests.test_deploy_dashboards.DeployDashboardsTests.test_load_manifest_returns_validated_resource_requirements -v
python -m unittest tests.test_deploy_dashboards.DeployDashboardsTests.test_load_manifest_rejects_unsafe_resource_requirements -v
```

Expected: `ERROR` because `load_manifest` does not exist.

- [ ] **Step 3: Implement `load_manifest` and preserve `load_entries`**

Refactor only the manifest-loading boundary:

```python
RESOURCE_TYPES = {"module", "css"}


def _validate_resource_requirements(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("invalid resource requirements")
    requirements = []
    seen = set()
    for requirement in value:
        if not isinstance(requirement, dict) or set(requirement) != {"type", "url_suffix"}:
            raise ValueError("invalid resource requirement")
        resource_type = requirement["type"]
        suffix = requirement["url_suffix"]
        if type(resource_type) is not str or resource_type not in RESOURCE_TYPES:
            raise ValueError("invalid resource type")
        if type(suffix) is not str or not suffix.startswith("/") or suffix.startswith("//"):
            raise ValueError("invalid resource suffix")
        parsed = urllib_parse.urlsplit(suffix)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path != suffix:
            raise ValueError("invalid resource suffix")
        key = (resource_type, suffix)
        if key in seen:
            raise ValueError("duplicate resource requirement")
        seen.add(key)
        requirements.append({"type": resource_type, "url_suffix": suffix})
    return requirements
```

Have `load_manifest` return:

```python
{
    "entries": entries,
    "resource_requirements": resource_requirements,
}
```

Keep all path-containment and config validation in the same protected `try` block. Make `load_entries` a wrapper:

```python
def load_entries(root, manifest_path):
    return load_manifest(root, manifest_path)["entries"]
```

- [ ] **Step 4: Write failing resource-preflight tests**

Extend `FakeClient` with a `lovelace/resources` result and a command record. Add tests for these exact contracts:

1. A required suffix and type match exactly one registered relative URL, even when the registered URL contains a runtime query token.
2. The exact registered URL is passed to the injected `resource_checker`, but the preflight report contains only `{"type", "url_suffix"}`.
3. Missing, duplicate, and wrong-type matches raise a safe `DeploymentError` that names only the sanitized suffix.
4. Absolute, scheme-relative, userinfo-bearing, or fragment-bearing registered resource URLs are rejected before `resource_checker` runs.
5. A token-like query value in the registered URL does not occur in errors, reports, or JSON artifacts.
6. With no dynamic requirements, the old four-argument `preflight(...)` behavior and fixed `REQUIRED_RESOURCES` checks stay unchanged.

Pass the new parameter by keyword to avoid changing existing injected checker calls:

```python
report = deploy_dashboards.preflight(
    client,
    "https://ha.example.test",
    TOKEN,
    self.entries,
    resource_checker=checker,
    resource_requirements=requirements,
)
```

- [ ] **Step 5: Run the focused preflight tests and observe failure**

Run:

```powershell
python -m unittest tests.test_deploy_dashboards.DeployDashboardsTests.test_preflight_verifies_dynamic_resources_without_persisting_runtime_url -v
python -m unittest tests.test_deploy_dashboards.DeployDashboardsTests.test_preflight_rejects_unsafe_registered_resource_urls -v
```

Expected: `FAIL` or `ERROR` because `preflight` does not accept or validate dynamic requirements.

- [ ] **Step 6: Implement safe runtime resource matching**

Add a helper that accepts only registered resource dictionaries whose `type` matches and whose parsed path ends with `url_suffix`. The registered URL must:

- be a nonempty string starting with exactly one `/`;
- have no scheme, network location, username, password, or fragment;
- remain same-origin and therefore safe for bearer-auth forwarding;
- be used only as the transient third argument to `resource_checker`.

Query text is allowed on a registered runtime URL because Scrypted uses it for access, but it must never be copied into reports or errors. Require exactly one match per requirement. Extend the signature without breaking old callers:

```python
def preflight(
    client,
    base_url,
    token,
    entries,
    resource_checker=http_resource_status,
    resource_requirements=(),
):
```

Only call `client.command({"type": "lovelace/resources"})` when requirements are present. Add this sanitized field to the returned report:

```python
"verified_resource_requirements": [dict(requirement) for requirement in resource_requirements]
```

Do not store the fetched resource registry or resolved URLs.

- [ ] **Step 7: Route the loaded requirements through `main`**

Replace the loader call with:

```python
manifest = load_manifest(root, args.manifest)
entries = manifest["entries"]
resource_requirements = manifest["resource_requirements"]
```

Then pass `resource_requirements=resource_requirements` into `preflight`. Update mocked `preflight` side effects in tests so their keyword-compatible signature includes `resource_requirements=()`.

- [ ] **Step 8: Run deployer tests**

Run:

```powershell
python -m unittest tests.test_deploy_dashboards -v
```

Expected: all deployer tests pass, including all prior rollback and credential-redaction cases.

- [ ] **Step 9: Commit Task 1**

```powershell
git add tools/deploy_dashboards.py tests/test_deploy_dashboards.py
git commit -m "feat: verify dynamic lovelace resources safely"
```

## Task 2: Add the isolated camera manifest and dashboard contract tests

**Files:**
- Create: `tools/scrypted_dashboard_manifest.yaml`
- Create: `tests/test_scrypted_dashboard_manifest.py`
- Create: `tests/test_luxury_cameras.py`

- [ ] **Step 1: Write the failing camera-manifest tests**

In `tests/test_scrypted_dashboard_manifest.py`, load only `tools/scrypted_dashboard_manifest.yaml` and assert:

```python
self.assertEqual([entry["url_path"] for entry in manifest["entries"]], ["luxury-cameras"])
self.assertEqual(manifest["entries"][0]["title"], "Luxury Cameras")
self.assertEqual(manifest["entries"][0]["icon"], "mdi:cctv")
self.assertEqual(manifest["entries"][0]["mode"], "storage")
self.assertIs(manifest["entries"][0]["show_in_sidebar"], True)
self.assertIs(manifest["entries"][0]["require_admin"], False)
```

Assert exact requirements:

```python
[
    {"type": "module", "url_suffix": "/hacsfiles/lovelace-layout-card/layout-card.js"},
    {"type": "module", "url_suffix": "/hacsfiles/button-card/button-card.js"},
    {"type": "module", "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.js"},
    {"type": "css", "url_suffix": "/endpoint/@scrypted/nvr/assets/web-components.css"},
]
```

Also assert that `tools/dashboard_manifest.yaml` remains exactly the original three paths and never contains `luxury-cameras`.

- [ ] **Step 2: Write failing dashboard-structure tests**

In `tests/test_luxury_cameras.py`, recursively walk `dashboards/luxury_cameras.yaml` and assert:

- exactly one view with `path: cameras`, `type: sections`, and `max_columns: 4`;
- headings contain `Luxury Cameras`, `LIVE NOW`, `ALL CAMERAS`, and `EVENT REEL`;
- camera card IDs are exactly `{107, 266, 267, 124, 287, 286, 289, 268, 288, 290, 269, 250, 264, 171, 173, 270, 271}` and occur once each;
- exactly IDs `[107, 266, 124, 268]` have `live: true`;
- every camera card has `type: custom:scrypted-nvr-camera`, `destination: low-resolution`, `imageClick: popup`, `videoClick: popup`, `theme: dark`, and `aspectRatio: 16/9`;
- no card contains `speakerOn` or `microphoneOn`;
- the event carousel has type `custom:scrypted-nvr-events-carousel`, `click: ha`, and no `ids` key;
- primary and secondary grids use 4 columns, then 2 columns at 1100px, then 1 column at 650px;
- navigation destinations are exactly `/luxury-home/home`, `/luxury-garage/garage`, and `/luxury-remote/remote`;
- YAML text contains no RFC1918 private IPv4 address and no credential markers (`access_token`, `Bearer`, `HA_TOKEN`, `token=`), and contains no URL with credentials/query strings;
- the two generic display labels `RTSP Camera A` and `RTSP Camera B` are present without embedding their private internal names.

- [ ] **Step 3: Run the new tests and observe failure**

Run:

```powershell
python -m unittest tests.test_scrypted_dashboard_manifest tests.test_luxury_cameras -v
```

Expected: `ERROR` because both YAML files are absent.

- [ ] **Step 4: Create the camera-only manifest**

Create `tools/scrypted_dashboard_manifest.yaml` with the exact four sanitized resource requirements above and one dashboard entry:

```yaml
dashboards:
  - url_path: luxury-cameras
    title: Luxury Cameras
    icon: mdi:cctv
    mode: storage
    show_in_sidebar: true
    require_admin: false
    config: dashboards/luxury_cameras.yaml
```

Keep `tools/dashboard_manifest.yaml` byte-for-byte unchanged.

- [ ] **Step 5: Commit the manifest and tests**

The dashboard tests should still fail because its YAML has not yet been created.

```powershell
git add tools/scrypted_dashboard_manifest.yaml tests/test_scrypted_dashboard_manifest.py tests/test_luxury_cameras.py
git commit -m "test: define scrypted camera dashboard contract"
```

## Task 3: Implement the responsive Luxury Cameras Lovelace dashboard

**Files:**
- Create: `dashboards/luxury_cameras.yaml`
- Modify only if tests expose a helper need: `tests/config_assertions.py`

- [ ] **Step 1: Create the top-level view and visual header**

Use a single view:

```yaml
title: Luxury Cameras
views:
  - title: Cameras
    path: cameras
    icon: mdi:cctv
    type: sections
    max_columns: 4
    dense_section_placement: true
    sections:
```

Build a dark header with the text `Luxury Cameras` and `17 cameras`, matching the rounded, dark visual language of the other Luxury dashboards. Do not reference HA entities.

- [ ] **Step 2: Add the four autoplay primary cameras**

Under `LIVE NOW`, use `custom:layout-card` with `layout_type: custom:grid-layout` and:

```yaml
layout:
  grid-template-columns: repeat(4, minmax(0, 1fr))
  grid-gap: 14px
  mediaquery:
    "(max-width: 1100px)":
      grid-template-columns: repeat(2, minmax(0, 1fr))
    "(max-width: 650px)":
      grid-template-columns: minmax(0, 1fr)
```

Add four cards in this order:

```yaml
- {id: 107, label: Front Door}
- {id: 266, label: Back Yard}
- {id: 124, label: Bedroom}
- {id: 268, label: Living Room}
```

Each actual camera card uses:

```yaml
type: custom:scrypted-nvr-camera
id: 107
live: true
destination: low-resolution
imageClick: popup
videoClick: popup
theme: dark
aspectRatio: 16/9
```

Do not add audio flags, HA service actions, or hard-coded Scrypted URLs.

- [ ] **Step 3: Add the thirteen click-to-play cameras**

Use the same responsive grid and the same camera settings, but omit the `live` key for all secondary cards. Use this exact ID and generic-label order:

```text
267 Back Yard 2
287 Blink Backyard
286 Blink Backyard 2
289 GNT2 Camera
288 Living Room 2
290 Mini Camera
269 OG Camera
250 RTSP Camera A
264 RTSP Camera B
171 Tapo C211 A
173 Tapo C211 B
270 U1
271 V4
```

Place the generic label above each of the two RTSP cards so the YAML and intended dashboard language never expose their raw private-host names. Because the Scrypted component resolves its own name from the numeric ID, make these two wrappers visually mask/crop the component's internal status-name strip while preserving the video viewport and popup click behavior. Use only already-required `stack-in-card`/`card-mod` resources, keep the masking CSS local to those two cards, and cover it with string-level tests that require both generic labels and the masking rule. The live rendered privacy check in Task 5 is the acceptance test; if the component still exposes a private address, do not rename the Scrypted device or accept the render—return to this CSS wrapper and adjust it.

- [ ] **Step 4: Add the all-camera event reel and navigation**

Use:

```yaml
type: custom:scrypted-nvr-events-carousel
click: ha
grid_options:
  columns: full
```

Omit `ids` so the official component includes all cameras. Add three responsive `custom:button-card` navigation cards linking exactly to the three existing view URLs. Navigation is the only `tap_action` in the dashboard.

- [ ] **Step 5: Run the camera tests**

Run:

```powershell
python -m unittest tests.test_scrypted_dashboard_manifest tests.test_luxury_cameras -v
```

Expected: all new tests pass.

- [ ] **Step 6: Run all static and deployer tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all 96 prior tests plus the new tests pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add dashboards/luxury_cameras.yaml tests/config_assertions.py
git commit -m "feat: add responsive luxury cameras dashboard"
```

If `tests/config_assertions.py` did not change, omit it from `git add`.

## Task 4: Document the camera-only operator workflow

**Files:**
- Modify: `README.md`
- Create: `tests/test_readme_camera_workflow.py`

- [ ] **Step 1: Write failing documentation tests**

Assert that the Responsive Luxury dashboard table includes:

```markdown
| Luxury Cameras | `/luxury-cameras/cameras` |
```

Assert README camera instructions include both commands:

```powershell
python tools/deploy_dashboards.py --manifest tools/scrypted_dashboard_manifest.yaml
python tools/deploy_dashboards.py --manifest tools/scrypted_dashboard_manifest.yaml --apply
```

Assert it says the camera manifest adds only `luxury-cameras`, requires the Scrypted integration/NVR frontend resources, uses the same credential-safe token handling, and gives camera-only cleanup for exactly `luxury-cameras`. Assert it does not add `luxury-cameras` to the cleanup sentence for the original three dashboards.

- [ ] **Step 2: Run the documentation test and observe failure**

Run:

```powershell
python -m unittest tests.test_readme_camera_workflow -v
```

Expected: `FAIL` because the camera workflow is undocumented.

- [ ] **Step 3: Update README without broad rewrites**

Add the fourth URL to the table. Directly after the existing deployment workflow, add a short `Luxury Cameras deployment` subsection that:

- points to the [official Scrypted Home Assistant documentation](https://docs.scrypted.app/home-assistant.html);
- explains that low-resolution autoplay is deliberate for HA responsiveness;
- reuses the secure prompt/process-scoped token pattern while adding the camera manifest argument;
- instructs operators to run dry-run first and apply only after it succeeds;
- states that registered dynamic Scrypted URLs are resolved in memory and only sanitized suffixes enter artifacts;
- gives a separate deletion path for exactly `luxury-cameras`.

Do not paste any current tokens, Scrypted proxy URLs, private camera addresses, or generated authorization values.

- [ ] **Step 4: Run documentation and full tests**

Run:

```powershell
python -m unittest tests.test_readme_camera_workflow -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add README.md tests/test_readme_camera_workflow.py
git commit -m "docs: add scrypted camera deployment workflow"
```

## Task 5: Perform credential-safe live preflight, deployment, and rendered acceptance

**Files:**
- Runtime-only ignored evidence: `artifacts/scrypted-camera-dashboard/`
- No tracked source changes unless live acceptance uncovers a tested implementation defect

- [ ] **Step 1: Re-run the full local verification gate**

Run:

```powershell
python -m unittest discover -s tests -v
git status --short
```

Expected: every test passes and the worktree is clean.

- [ ] **Step 2: Reconfirm the live Scrypted inventory and license without logging authorization**

Use read-only HA config-entry and resource commands to confirm the `scrypted` entry remains loaded and its NVR module/CSS registrations are present. Then use the official Scrypted client in one process with `console.log` temporarily suppressed before connection construction. Compare the live devices implementing Camera against this exact ID set:

```text
107, 124, 171, 173, 250, 264, 266, 267, 268, 269, 270, 271, 286, 287, 288, 289, 290
```

Confirm the total is 17 and the NVR license remains active. Restore logging only after the client is disconnected, clear all generated authorization state, and persist only counts, numeric IDs, and booleans. If any ID is absent, the NVR is unlicensed, or the entry is not loaded, block apply.

- [ ] **Step 3: Run a camera-only live dry run**

Use the user-supplied temporary HA token only in the current process environment. Never print it. Invoke:

```powershell
python tools/deploy_dashboards.py `
  --manifest tools/scrypted_dashboard_manifest.yaml `
  --artifact-dir artifacts/scrypted-camera-dashboard
```

Expected report:

- `status: dry-run`;
- target path exactly `luxury-cameras`;
- four sanitized resource requirements verified;
- no collision with dashboards or panels;
- no entity requirements;
- no mutation.

Scan generated JSON for credential markers and for the current token value without displaying matches. The scan must be clean before apply.

- [ ] **Step 4: Apply the camera-only manifest**

Run the same command with `--apply`. Expected result:

- exactly one created dashboard, `luxury-cameras`;
- the three existing Luxury dashboard records and configs remain byte-for-byte unchanged in readback;
- the saved camera config equals `dashboards/luxury_cameras.yaml` structurally;
- artifacts contain no raw credential, Scrypted runtime URL, or private camera address.

Immediately remove the token environment variable after the command, including on failure.

- [ ] **Step 5: Verify live registry and configuration readback**

With a new short process-scoped token assignment only if required, use the HA WebSocket API read-only commands to confirm:

```text
lovelace/dashboards/list -> one luxury-cameras record
lovelace/config url_path=luxury-cameras -> exact local YAML structure
```

Record only sanitized counts, IDs, and config hashes. Never record authorization or dynamic resource URLs.

- [ ] **Step 6: Verify the rendered dashboard responsively**

Open `https://kcam-hassio.duckdns.org:8123/luxury-cameras/cameras` in the in-app browser after the user completes HA authentication. Inspect desktop, tablet, and phone viewport widths and confirm:

- grids change 4 → 2 → 1 columns;
- only the four primary feeds autoplay and they use the low-resolution destination;
- all thirteen secondary camera tiles are present and open on click;
- the event reel renders and opens events;
- there are no missing-resource/error cards;
- navigation reaches the three pre-existing Luxury view URLs;
- no private host address appears anywhere, especially on IDs 250 and 264;
- no speaker or microphone starts automatically.

Capture screenshots only if they contain no credentials or private-address text. If any acceptance check fails, add/adjust a failing automated test first, implement the smallest source change, rerun all tests, and redeploy only `luxury-cameras` through a safe update path. Do not delete or recreate the original dashboards.

- [ ] **Step 7: Final secret scan and status check**

Run a tracked-source and artifact scan for:

```text
access_token
Authorization: Bearer
HA_TOKEN
token=
192.168.100.246
192.168.40.90
```

Known documentation examples that mention the variable name `HA_TOKEN` are allowed only where already intentional; no value may be present. Confirm `git status --short` contains no uncommitted tracked changes and review the final commit range.

- [ ] **Step 8: Independent final review**

Have a fresh reviewer compare the approved spec, this plan, all new commits, test output, sanitized live evidence, and rendered screenshots. Resolve every substantive finding with tests before declaring completion.
