# Project Memory — ai-stack / GOAT HA Integration

## Active work

All Ecovacs GOAT mower work lives in `goat-a3000/`.

Files prefixed `ecovacs-repo-` are **staging copies** destined for the separate
`Rico36/Ecovacs-Goat-A3000-Mower` repo. GitHub MCP access here is scoped to
`rico36/ai-stack` only, so those files are pushed to this branch and then
`curl`ed onto the Pi and committed to the other repo from there.

### Files

| File | Purpose |
|---|---|
| `goat-a3000/goat_mower_garage.yaml` | HA package — all helpers, scripts, automations |
| `goat-a3000/dashboard.yaml` | HA dashboard card YAML (reference copy) |
| `goat-a3000/README.md` | deebot-client patch docs |
| `goat-a3000/validate-patches.sh` | Verifies deebot-client patches are active in container |
| `goat-a3000/patch-rs-imports.py` | aarch64 fallbacks for the Rust extension (9 import sites) |
| `goat-a3000/ecovacs-repo-README.md` | Staged root README for the Ecovacs repo |
| `goat-a3000/ecovacs-repo-HA-readme.md` | Staged `HA/readme.md` for the Ecovacs repo |
| `goat-a3000/ecovacs-repo-patches-clean.py` | Staged patched `clean.py` |
| `goat-a3000/ecovacs-repo-patches-51rcxt.py` | Standby Pro hardware profile — **not deployed** |

### Hardware

- Mower: **GOAT A3000 LiDAR Pro**, class `51rcxt`
  (model `GOAT_INT_A2600_LIDAR_PLUS_NA`, UILogicId `goatl_ww_h_goat2plus`)
  — replacing the GOAT A3000 LiDAR, class `cr0e4u`, fw 1.13.31
- **No garage.** The Pro bases in the backyard in its own weather housing.
- Backyard gate: `binary_sensor.backyard_gate_contact` — HA can **read but not
  control** it. `off` = closed (assumed; verify). It is the physical
  prerequisite for reaching the front zones.
- HA: Docker container `home-assistant` on Raspberry Pi (aarch64)
- Soil moisture: `sensor.front_rain_sensor_soil_moisture` (THIRDREALITY Gen2 Zigbee)
- Also on dashboard: `sensor.lawn_front_soil_moisture`, `sensor.lawn_back_soil_moisture`
- External dependency referenced by reminders: `sensor.goat_rain_last_3_hours`

### Zone IDs — Pro (`51rcxt`), confirmed Sept 2026

| App area | Internal ID |
|---|---|
| Front | 3 |
| Side | 2 |
| Backyard | **1** |

Discovered by mowing Front → Side → Backyard from the app and reading
`onCleanInfo … "type":"spotArea","value":"3,2,1"`. **The value list is mow
order**, not app-area order — verified deliberately.

`goat_gate_free_zones` = `1` (Backyard is the mower's own side of the gate).

Old cr0e4u mapping, superseded: `3,2,6,4,7,5` over six areas.

---

## Ecovacs integration — the July 2026 situation

Stock integration broke: Ecovacs added server-side email device verification
(error 1013). Running the **community custom integration** at
`/config/custom_components/ecovacs/` (= `/home/admin/homeassistant/…`), which
vendors its own deebot_client (18.4.0 base, manifest `2026.7.2-email-device-auth.1`).

Consequences to remember:

- Patches now live in `custom_components/ecovacs/vendor/deebot_client/`,
  **not** site-packages. They survive container updates (mounted volume).
- The bundled Rust extension is x86_64-only → all 9 `deebot_client.rs` import
  sites are wrapped in try/except with pure-Python stubs. **Map rendering is
  off** (`generate_svg` returns None); everything else works.
- **Do not update HA core casually** — the custom integration is pinned to
  2026.7.2 internals and the mower depends on it.
- PirateWeather is **pinned to v1.9.0**; v1.9.2 needs `UnitOfDensity`, absent
  from this HA core. Ignore the HACS update badge.

### Live patches in the vendored library

| File | Patch |
|---|---|
| `hardware/cr0e4u.py` | `GetCleanInfo` (not V2), clean action → `CleanMowerArea` |
| `commands/json/clean.py` | `CleanMower`/`CleanMowerArea`; task-type cache for RESUME; `workComplete` marker |
| `messages/json/__init__.py` | routes `onScheduleTaskInfo`; `goCharging` → RETURNING |

Two `clean.py` findings worth keeping:
- **RESUME must echo the running task's type.** Resuming a `spotArea` task with
  `type: auto` returns `code 0 "ok"` and is silently ignored. The task type is
  cached from `getCleanInfo`/`onCleanInfo`.
- **`workComplete` is the only reliable end-of-run signal.** Battery level
  cannot distinguish an end-of-run dock from a mid-run recharge — runs have
  completed at 17%. The patch writes `/tmp/goat_work_complete`; HA reads its
  freshness via `shell_command.goat_check_work_complete` (< 20 min = complete).

---

## goat_mower_garage.yaml — current state

### Key design decisions

- **Scheduling**: HA is the sole scheduler; all Ecovacs app schedules deleted.
- **Three mow paths** — scheduled (`goat_mowing_start`), manual
  (`goat_start_mowing_now`), makeup (`GOAT - Makeup Day Check`) — all read
  `goat_mow_mode` + `goat_zone_ids`, write the zone file, call `start_mowing`.
- **Rain forecast**: PirateWeather 95-min window; blocks at
  `precipitation_probability >= 40%` or rainy/pouring/lightning.
- **Mow gate**: Grass Status `Wet` blocks; `Dry` passes; `Uncertain` falls back
  to raw moisture ≥ 55%.
- **Departure Handler** handles *every* non-HA departure (app start, physical
  button, recharge self-resume) with one flow: **pause first, decide second** —
  halt the mower immediately, then weather-check, then dock or resume.
  `goat_departure_window_active` is what excludes HA-initiated starts.
- **Critical notifications**: errors, paused-too-long, not-docked-after-2h, and
  a gate still closed at T−5.

### Grass Status — priority chain (`GOAT - Update Grass Status`)

| # | Rule | Condition | Result |
|---|---|---|---|
| P1 | Floor dry | m < 55 AND not morning | Dry, clears flags |
| P2 | Delta spike | Dry AND m − 30-min-min > **3** | Wet; baseline ← 30-min min |
| P3 | Override hold | override on, not expired | hold |
| P4 | Delta cancel | delta on AND m ≤ baseline **+ 1** | Dry; baseline ← m |
| P5 | Delta hold | delta on | hold Wet |
| P6 | Morning dew | 4–10 AM AND m > 51 | Wet (unconditional) |
| P7 | High moisture | m > 79 AND m > baseline | Wet |
| P8 | Normal dry | m ≤ baseline (fallback 69) | Dry |

**Dry baseline** (`input_number.goat_moisture_baseline`) is set **only** by
manual Dry (current m) and delta scenarios; cleared by manual Wet. Never set
from an unvalidated reading, never reset on a schedule. A 10am snapshot rule
was tried and removed — it declared Dry prematurely and ratcheted the baseline
upward every wet morning.

Manual override locks status for 5 hours (`GOAT - Expire Manual Override`);
only a delta spike can override it.

### Entities

**input_boolean** — `goat_automation_enabled`, `goat_departure_window_active`
(HA-initiated start in flight), `goat_mowing_session_active`,
`goat_schedule_mon…sun`, `goat_makeup_pending`, `goat_grass_status_override`,
`goat_delta_rule_active`

**input_number** — `goat_moisture_baseline`

**input_select** — `goat_mow_mode`, `goat_grass_status` (Uncertain/Dry/Wet)

**input_datetime** — `goat_mowing_start_time`, `goat_mowing_session_started_at`,
`goat_last_mowing_decision`, `goat_override_started_at`

**input_text** — `goat_last_mowing_status`, `goat_zone_ids`

**sensor** — `soil_moisture_30min_min` (statistics, `value_min`, 30 min)

**shell_command** — `goat_write_zones`, `goat_check_work_complete`

### Scripts

`goat_notify`, `goat_try_dock` (dock twice, 20s apart), `goat_mowing_start`,
`goat_test_weather_check`, `goat_start_mowing_now`

### Automations (15)

Scheduled Start Gatekeeper · Departure Handler · Paused Too Long Return To
Dock · Mower Returning · Clear Departure Window · Error After Mowing Started ·
Session End On Dock · Session Cleanup After Long Charge (3h) · Not Docked
Fallback Alert (+120 min) · Makeup Day Check · Update Grass Status · Lock Grass
Status On Manual Override · Expire Manual Override · Mowing Day Reminder
(T−17) · Pre-Start Reminder (T−5)

Both reminders are gate-aware: T−17 only asks for the gate if it's closed; T−5
escalates to a critical phone alert if it's still shut.

---

## Open items

- **Pro cutover**: entity renaming (38 refs — easiest is to reassign the old
  entity IDs to the Pro after removing the A3000), new zone IDs, and retuning
  the 95-min / 120-min windows (the Pro has a 7500 mAh battery vs 5000, so
  runtime differs and mid-run recharges may stop happening).
- **`51rcxt` profile**: upstream ships one, so the device enumerates, but its
  stock `CleanV2` wiring **is confirmed broken on the Pro** — HA's pause sends
  `content: {"type": ""}` and the mower does not reply at all, while the app's
  pause with `{"type": "spotArea"}` is accepted. Deploy
  `ecovacs-repo-patches-51rcxt.py`. Note `lawn_mower.dock` always worked: it
  maps to the `charge` command, a different endpoint from `clean`.
  Still unverified: whether `GetCleanInfoV2` answers on the Pro (it timed out
  with errno 500 on cr0e4u), and whether HA-initiated *start* works.
- **Undecided**: should a closed gate at dispatch time cancel the mow (with
  makeup pending) or proceed and mow only the backyard?
- **Dashboard** still has garage rows and a `mdi:garage-alert` icon.
- `validate-patches.sh` hardcodes `cr0e4u.py` and site-packages paths.
