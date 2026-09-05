# Ecovacs GOAT A3000 LiDAR — Home Assistant Integration

Full Home Assistant integration for the GOAT A3000 LiDAR mower: deebot-client
patches to make the mower work at all, plus a complete HA automation package
that replaces the Ecovacs app as the scheduler.

---

## Part 1 — deebot-client patches

### Tested environment

| Component | Version / detail |
|---|---|
| Mower | GOAT A3000 LiDAR, class `cr0e4u`, fw 1.13.31. Also running a **GOAT A3000 LiDAR Pro**, class `51rcxt` — see "The Pro" below |
| Home Assistant | Container install (Docker), container name `home-assistant` |
| Host | Raspberry Pi, Raspberry Pi OS (64-bit) |
| Ecovacs integration library | deebot-client **18.3.0** (site-packages, classic setup). Since July 2026 the active copy is the community custom integration's vendored deebot-client, based on **18.4.0** (email device verification / error 1013 fix) |
| Python inside the HA container | 3.14 (`/usr/local/lib/python3.14/site-packages/`) |
| Container updates | Watchtower (see "Surviving container updates") |

Not tested on: HA OS or HA Supervised (no direct `docker exec` access to
the HA container there), other GOAT models, other firmware versions.

**The deebot-client version matters.** All three patches are
full-file replacements. Applying them over a different library version
will silently revert unrelated upstream changes in those files. If your
version differs from 18.3.0, diff the patches against your installed files
and port the changes by hand (they are small; see "The patches" below).
Check your version with:

```bash
docker exec home-assistant python -c \
  "import importlib.metadata; print(importlib.metadata.version('deebot-client'))"
```

### The problems

Stock deebot-client treats the A3000 like a vacuum. Four things break:

| Symptom | Cause |
|---|---|
| State stuck on "Docked" forever | Library polls `getCleanInfo_V2`; the A3000 never answers (20s timeout, every poll) |
| Start/pause/stop from HA do nothing | Library sends to `clean_V2` endpoint; the A3000 wants `clean` with `{"type": "auto"}` |
| "Returning" never shown | Returning signal arrives in `onChargeInfo` (`state: goCharging`), which the library drops |
| Scheduled sessions show wrong state | Schedule-started sessions push `onScheduleTaskInfo`, unknown to the library |

### The patches

Three files, drop-in replacements for the ones inside the HA container:

- **`patches/cr0e4u.py`** replaces `deebot_client/hardware/cr0e4u.py`.
  Swaps `GetCleanInfoV2` for `GetCleanInfo` (the A3000 answers this one)
  and wires the clean action to `CleanMowerArea`.

- **`patches/clean.py`** replaces `deebot_client/commands/json/clean.py`.
  Adds `CleanMower` and `CleanMowerArea` command classes. `CleanMowerArea`
  reads `/tmp/goat_zones` (comma-separated zone IDs written by HA before
  each mow) and sends `{"type": "spotArea", "value": "..."}`. Falls back
  to `{"type": "auto"}` when the file is absent.

- **`patches/messages_json_init.py`** replaces `deebot_client/messages/json/__init__.py`.
  Two additions: routes `onScheduleTaskInfo` to the getCleanInfo handler
  (fixes scheduled-session state), and adds a guarded `onChargeInfo` handler
  that maps `state == "goCharging"` to RETURNING.

### Install

```bash
git clone https://github.com/Rico36/ai-stack.git
cd ai-stack/goat-a3000
./validate-patches.sh
```

Adjust the container name and site-packages path at the top of the script
if yours differ. Check your Python path with:

```bash
docker exec home-assistant find /usr/local/lib -name "cr0e4u.py"
```

### Surviving container updates

Anything that recreates the container (Watchtower, image update) wipes the
patches. `validate-patches.sh` checks a sentinel and reapplies only when
needed. It is safe to run hourly: it does nothing (no restart) when the
patches are intact. Root crontab:

```
0 * * * * /home/admin/goat-a3000/validate-patches.sh >> /home/admin/patch.log 2>&1
```

### July 2026 — Ecovacs auth change (error 1013)

Ecovacs changed authentication server-side in July 2026: logins now
require email device verification, and every deebot-client release fails
with error 1013 ("Please update"). The fix is a community custom
integration with the new auth flow installed at
`/config/custom_components/ecovacs/` (see
[home-assistant/core #176484](https://github.com/home-assistant/core/issues/176484)),
with the three GOAT patches re-applied to its vendored
`vendor/deebot_client/` copy.

On ARM hosts (Raspberry Pi), the custom integration's bundled Rust
extension is x86_64-only and the integration fails to load with
`ModuleNotFoundError: No module named 'deebot_client.rs.map'`.
`patch-rs-imports.py` in this folder wraps all nine `deebot_client.rs`
import sites with pure-Python fallbacks — map image rendering is lost,
mowing control and state are unaffected:

```bash
sudo python3 patch-rs-imports.py
sudo find /home/admin/homeassistant/custom_components/ecovacs/vendor -name '*.pyc' -delete
docker restart home-assistant
```

### Zone IDs

Zone IDs are internal library IDs, **not** the area numbers shown in the
Ecovacs app. Find yours by enabling debug logging for the mower, starting an
area mow from the app, then searching the logs for:

```
onCleanInfo ... "type":"spotArea","value":"..."
```

The values appear in the order the app lists the areas, so mowing one area
alone reveals that area's internal ID. Put them, comma-separated and in mow
order, into `input_text.goat_zone_ids`.

---

## Part 2 — HA automation package

`goat_mower_garage.yaml` is a complete HA package. Drop it in your
`/config/packages/` folder and reload. It replaces the Ecovacs app as
the sole scheduler — delete all Ecovacs app schedules after deploying.

### What it does

- **Scheduled mowing**: fires at a configurable daily time on selected days,
  runs the full pre-flight check, and commands `lawn_mower.start_mowing`
- **Manual mowing**: "Start Mowing Now" button runs the same checks
- **Makeup mowing**: a weather-cancelled mow retries hourly 11am–7pm on
  non-scheduled days until conditions clear
- **Grass Status**: an eight-rule priority chain over soil moisture that
  distinguishes dew, rain spikes and genuine dryness, with a manual override
  that also calibrates the dry threshold. This is the heart of the package —
  see `HA/readme.md` in the companion repo for the full rule table
- **Rain forecast**: blocks when PirateWeather shows ≥ 40% precipitation
  probability, or a rainy/pouring/lightning condition, in the next 95 minutes
- **Departure handling**: any start HA did not initiate — app, physical
  button, or the mower resuming after a mid-run recharge — is paused
  immediately, weather-checked, then either docked or resumed
- **Mid-run recharge**: distinguishes a charging break from a finished run
  using the mower's `workComplete` signal, so the session is not closed out
  early (battery level cannot tell them apart — runs finish as low as 17%)
- **Error handling**: critical push + dock on mower error or a pause over
  5 minutes; fallback alert if still out after 2 hours

### Optional: a physical barrier before mowing

This package was originally built around a garage door the mower had to pass
through. That is gone — the mower now bases outdoors — but the pattern
survives for anyone whose mower must cross a gate to reach part of the lawn:

- Two pre-mow reminders (T−17 and T−5) check a contact sensor and only ask
  for the barrier when it is actually shut
- They stay quiet when the scheduled zones are all reachable without it
  (`input_text.goat_gate_free_zones`)
- T−5 escalates to a critical push if it is still closed

If you have no such barrier, leave `binary_sensor.backyard_gate_contact`
undefined and the reminders simply always mention it — or delete the two
reminder automations.

### External dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| PirateWeather integration | 95-minute rain forecast (`weather.pirateweather`) | yes |
| THIRDREALITY Soil Moisture Sensor Gen2 (Zigbee) | Grass Status (`sensor.front_rain_sensor_soil_moisture`) | yes |
| iOS Companion App | Push notifications via `notify.house_phones` | yes |
| Alexa Media Player | Spoken pre-mow reminders via `notify.house_alexas` | reminders only |
| Gate/door contact sensor | `binary_sensor.backyard_gate_contact` | reminders only |
| Rain accumulation sensor | `sensor.goat_rain_last_3_hours` | reminders only |

Any soil moisture sensor works; only the entity ID matters. Every mower
reference is `lawn_mower.goat_a3000_lidar_pro` plus its `_error` and `_battery`
sensors — rename your entities to match and no YAML edits are needed.

### Configuration — after deploying the package

1. **Set your mowing days** — tap Mon–Sun buttons on the dashboard
2. **Set your start time** — `Scheduled Start Time` input on the dashboard
3. **Set your mow mode** — "Areas" or "Full Map (Auto)"
4. **Set your zone IDs** — comma-separated (see Zone IDs above)
5. **Set gate-free zones** — IDs reachable without opening the gate; leave
   empty if you have no gate
6. **Set the dry baseline** — set Grass Status to `Dry` manually on a day the
   lawn genuinely is; that records the threshold everything else measures
   against
7. **Enable automation** — `GOAT Automation Enabled` toggle
8. **Delete all Ecovacs app schedules** — HA is now the scheduler

### Tuning for your yard

Two timers assume a roughly 95-minute run and are the first things to adjust:
`start + 95 min` opens the expected-return window, and `start + 120 min`
raises a critical "not docked" alert. Time two or three full runs and set them
from real data, especially on a mower with a different battery.

### Dashboard

`dashboard.yaml` contains the reference card YAML. Paste it into your
dashboard via the raw config editor. Requires two HACS frontend cards:

- `custom:button-card` — day-of-week selector grid
- `custom:template-entity-row` — session status rows

Layout:
1. Entities card — status + scheduled mowing (time, mode, zone IDs)
2. 7-column button grid — Mon–Sun selectors (green = scheduled, grey = off)
3. Entities card ("Mowing Run") — manual start + session status

---

## The Pro (class `51rcxt`)

The GOAT A3000 LiDAR **Pro** reports class `51rcxt` (model
`GOAT_INT_A2600_LIDAR_PLUS_NA`, UILogicId `goatl_ww_h_goat2plus`) — a
different platform from the A3000, despite the shared name. deebot-client
18.4.0 already ships `hardware/51rcxt.py`, so the device enumerates with no
new definition needed.

That stock profile does wire `CleanV2`, `CleanAreaV2` and `GetCleanInfoV2` —
the same V2 pattern that fails on `cr0e4u`. Whether the Pro's firmware
answers them is hardware-specific: test before assuming it needs the patches.
If it does, the fix is three lines (swap in `GetCleanInfo` and
`CleanMowerArea`); the two profiles are otherwise byte-identical.

The Pro also carries a 7500 mAh battery against the A3000's 5000 mAh, so
mid-run recharges may stop happening entirely and the 95/120-minute timers
will need retuning.

## Findings reference

For anyone debugging other GOAT models, observed on cr0e4u fw 1.13.31:

- `getCleanInfo` answers; `getCleanInfo_V2` times out (errno 500).
- `getCleanInfo` returns `idle` during scheduled sessions. The app uses
  `getScheduleTaskInfo` as the authoritative state source.
- HA/app-started sessions push `onCleanInfo` continuously (handled by the
  library's legacy fallback). Schedule-started sessions push
  `onScheduleTaskInfo` instead.
- During return-to-dock, `onCleanInfo` reports `motionState: "pause"` the
  whole way. `goCharging` only ever appears in `onChargeInfo`.
- Error pipeline (`getError` / `onError`) works natively. Observed mower
  code: **640 = LiDAR blocked** (e.g. cover left on). Not in the library's
  `_ERROR_CODES`, so HA shows the bare number.
- Unhandled events still dropped (telemetry, no functional impact):
  `onArI`, `onMapTrace`, `onMI`, `onScheduleLatestTask`,
  `onFwBuryPoint-bd_*` (battery stats, task lifecycle, GPS).

## Status upstream

- [PR #1515](https://github.com/DeebotUniverse/client.py/pull/1515) adds
  `CleanMower` for GOAT mowers. These patches confirm the approach on
  cr0e4u hardware.
- [Issue #1574](https://github.com/DeebotUniverse/client.py/issues/1574) is
  the A3000 support request.

Once upstream ships native support, delete the cron line and let the
container update normally.

## Credits

- [@reniko](https://github.com/reniko): `CleanMower` command design
  ([PR #1515](https://github.com/DeebotUniverse/client.py/pull/1515))
- [@shinerblue](https://github.com/shinerblue): iOS MQTT captures proving
  `{"type": "auto"}` for all four clean actions

## Disclaimer

These patches modify library files inside the HA container at your own
risk. They are version-specific (deebot-client 18.3.0). After a major
library update, diff before reapplying.
