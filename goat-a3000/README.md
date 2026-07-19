# Ecovacs GOAT A3000 LiDAR — Home Assistant Integration

Full Home Assistant integration for the GOAT A3000 LiDAR mower: deebot-client
patches to make the mower work at all, plus a complete HA automation package
that replaces the Ecovacs app as the scheduler.

---

## Part 1 — deebot-client patches

### Tested environment

| Component | Version / detail |
|---|---|
| Mower | GOAT A3000 LiDAR, model `cr0e4u`, firmware 1.13.31 |
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

### Zone IDs (cr0e4u)

Zone IDs are internal library IDs, not the area numbers shown in the Ecovacs
app. Find yours by enabling debug logging for the mower in HA, starting a
zone mow from the app, then searching the logs for:

```
onCleanInfo ... "type":"spotArea","value":"3,2,6,4,7,5"
```

Confirmed IDs on this hardware:

| Zone ID | Area |
|---|---|
| 2 | Front Street |
| 3 | Front |
| 4 | Left Side Street |
| 5 | Backyard Side |
| 6 | Left Side |
| 7 | Backyard |

---

## Part 2 — HA automation package

`goat_mower_garage.yaml` is a complete HA package. Drop it in your
`/config/packages/` folder and reload. It replaces the Ecovacs app as
the sole scheduler — delete all Ecovacs app schedules after deploying.

### What it does

- **Scheduled mowing**: fires at a configurable daily time on selected days,
  checks weather, opens the garage, and commands `lawn_mower.start_mowing`
- **Manual mowing**: "Start Mowing Now" button on the dashboard runs the
  same weather check and mow flow
- **Makeup mowing**: if a scheduled mow is weather-cancelled, retries
  automatically every hour 11am–7pm on non-scheduled days until conditions clear
- **Garage management**: opens before mowing, closes after departure; opens
  again when mower returns; closes when docked
- **Weather protection**: blocks mowing if soil moisture ≥ 55% (wet grass /
  dew / rain) or if PirateWeather forecasts ≥ 40% precipitation probability
  in the next 95 minutes
- **Error handling**: critical iOS alert + dock command on mower error or
  pause > 5 minutes; fallback alert if mower is still out after 2 hours

### External dependencies

| Dependency | Purpose |
|---|---|
| PirateWeather integration | 95-minute rain forecast (`weather.pirateweather`) |
| THIRDREALITY Soil Moisture Sensor Gen2 (Zigbee) | Wet grass detection (`sensor.front_rain_sensor_soil_moisture`) |
| iOS Companion App | Push notifications via `notify.house_phones` |
| `cover.garage_door` | Garage door entity (any cover integration) |

### Configuration — after deploying the package

1. **Set your mowing days** — tap Mon–Sun buttons on the dashboard
2. **Set your start time** — `Scheduled Start Time` input on the dashboard
3. **Set your mow mode** — "Areas" or "Full Map (Auto)"
4. **Set your zone IDs** — comma-separated (see Zone IDs above)
5. **Enable automation** — `GOAT Automation Enabled` toggle
6. **Delete all Ecovacs app schedules** — HA is now the scheduler

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
