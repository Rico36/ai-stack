# Ecovacs GOAT A3000 LiDAR - Home Assistant patches

Working patches for the deebot-client library to get the GOAT A3000 LiDAR
(model `cr0e4u`) fully working in Home Assistant: start/pause/resume/stop/dock
from HA, correct live state (Mowing / Paused / Returning / Docked / Error),
and working error codes.

Everything here was verified against real hardware with MQTT debug logs.
No guesswork.

## Tested environment

These patches were built and verified on exactly this setup. The closer
yours matches, the more likely they work unmodified.

| Component | Version / detail |
|---|---|
| Mower | GOAT A3000 LiDAR, model `cr0e4u`, firmware 1.13.31 |
| Home Assistant | Container install (Docker), container name `home-assistant` |
| Host | Raspberry Pi, Raspberry Pi OS (64-bit) |
| Ecovacs integration library | deebot-client **18.3.0** |
| Python inside the HA container | 3.14 (`/usr/local/lib/python3.14/site-packages/`) |
| Container updates | Watchtower (see "Surviving container updates") |

Not tested on: HA OS or HA Supervised (no direct `docker exec` access to
the HA container there), other GOAT models, other firmware versions.

**The deebot-client version matters.** Two of the three patches are
full-file replacements. Applying them over a different library version
will silently revert unrelated upstream changes in those files. If your
version differs from 18.3.0, diff the patches against your installed files
and port the changes by hand (they are small; see "The patches" below).
Check your version with:

```bash
docker exec home-assistant python -c "import deebot_client; print(deebot_client.__version__)"
```

## The problems

Stock deebot-client treats the A3000 like a vacuum. Four things break:

| Symptom | Cause |
|---|---|
| State stuck on "Docked" forever | Library polls `getCleanInfo_V2`; the A3000 never answers (20s timeout, every poll) |
| Start/pause/stop from HA do nothing | Library sends to `clean_V2` endpoint; the A3000 wants `clean` with `{"type": "auto"}` |
| "Returning" never shown | Returning signal arrives in `onChargeInfo` (`state: goCharging`), which the library drops |
| Scheduled sessions show wrong state | Schedule-started sessions push `onScheduleTaskInfo`, unknown to the library |

## The patches

Three files, drop-in replacements for the ones inside the HA container:

- **`patches/cr0e4u.py`** replaces `deebot_client/hardware/cr0e4u.py`.
  Swaps `GetCleanInfoV2` for `GetCleanInfo` (the A3000 answers this one)
  and wires the clean action to `CleanMower`.

- **`patches/clean.py`** replaces `deebot_client/commands/json/clean.py`.
  Adds a `CleanMower` command class: `clean` endpoint, `{"type": "auto"}`
  payload for all four actions. Note: `"area"` and `""` are both rejected by
  the A3000 with `msg: "unknow type"`, and the response carries `code: 0`,
  so it fails silently if you only check the code.

- **`patches/messages_json_init.py`** replaces `deebot_client/messages/json/__init__.py`.
  Two additions: routes `onScheduleTaskInfo` to the getCleanInfo handler
  (fixes scheduled-session state), and adds a guarded `onChargeInfo` handler
  that maps `state == "goCharging"` to RETURNING. The guard matters: after
  docking the same message fires with `state: "idle"`, and mapping that
  overrides DOCKED with IDLE (HA shows it as "Paused").

## Install

```bash
git clone https://github.com/Rico36/Ecovacs-Goat-A3000-Mower.git
cd Ecovacs-Goat-A3000-Mower
./scripts/apply-patches.sh
```

The script copies the three files into the `home-assistant` container,
clears the Python bytecode caches (`__pycache__`; skip this and the old
code keeps running), and restarts HA.

Adjust the container name and the site-packages path at the top of the
script if yours differ. The path includes the Python version
(`python3.14` here). Check yours with:

```bash
docker exec home-assistant find /usr/local/lib -name "cr0e4u.py"
```

## Surviving container updates

Anything that recreates the container (Watchtower, image update) wipes the
patches. `scripts/check-patches.sh` checks a sentinel and reapplies only
when needed. It is safe to run hourly: it does nothing (no restart) when
the patches are intact. Root crontab:

```
0 * * * * /home/admin/goat-a3000/scripts/check-patches.sh >> /home/admin/patch.log 2>&1
```

Adjust the path to wherever you cloned the repo.

## Findings reference

For anyone debugging other GOAT models, observed on cr0e4u fw 1.13.31:

- `getCleanInfo` answers; `getCleanInfo_V2` times out (errno 500).
- `getCleanInfo` returns `idle` during scheduled sessions. The app uses
  `getScheduleTaskInfo` as the authoritative state source, which is not
  implemented in the library yet.
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
