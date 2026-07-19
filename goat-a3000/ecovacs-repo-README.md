# Ecovacs GOAT A3000 LiDAR - Home Assistant patches

Working patches for the deebot-client library to get the GOAT A3000 LiDAR
(model `cr0e4u`) fully working in Home Assistant: start/pause/resume/stop/dock
from HA, correct live state (Mowing / Paused / Returning / Docked / Error),
and working error codes.

Everything here was verified against real hardware with MQTT debug logs.
No guesswork.

> **July 2026:** Ecovacs changed their login flow server-side and broke the
> stock integration for everyone (error 1013 "Please update"). If your
> integration suddenly stopped authenticating, jump to
> [July 2026 — Ecovacs auth change](#july-2026--ecovacs-auth-change-error-1013).

## Tested environment

These patches were built and verified on exactly this setup. The closer
yours matches, the more likely they work unmodified.

| Component | Version / detail |
|---|---|
| Mower | GOAT A3000 LiDAR, model `cr0e4u`, firmware 1.13.31 |
| Home Assistant | Container install (Docker), container name `home-assistant` |
| Host | Raspberry Pi, Raspberry Pi OS (64-bit) |
| Ecovacs integration library | deebot-client **18.3.0** (site-packages, classic setup). Since July 2026 the active copy is the custom integration's vendored deebot-client, based on **18.4.0** — see the July 2026 section |
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

(The library has no `__version__` attribute, so `deebot_client.__version__`
does not work. This reports the pip-installed site-packages copy; the
vendored copy in the custom integration carries no version metadata —
check the custom integration's `manifest.json` instead.)

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
  and wires the clean action to `CleanMowerArea`.

- **`patches/clean.py`** replaces `deebot_client/commands/json/clean.py`.
  Adds two command classes. `CleanMower`: `clean` endpoint (not `clean_V2`),
  `{"type": "auto"}` payload for all four actions. Note: `"area"` and `""`
  are both rejected by the A3000 with `msg: "unknow type"`, and the response
  carries `code: 0`, so it fails silently if you only check the code.
  `CleanMowerArea` (what cr0e4u.py actually uses): on START, reads
  comma-separated zone IDs from `/tmp/goat_zones` inside the container
  (written by HA before each mow), sends
  `{"type": "spotArea", "value": "..."}`, and deletes the file so stale
  zones never leak into the next run. If the file is absent or empty it
  falls back to full-auto, identical to `CleanMower`.

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

## July 2026 — Ecovacs auth change (error 1013)

In July 2026 Ecovacs changed authentication **server-side**: logins now
require an email device-verification step. Every deebot-client release to
date (including 18.4.0) fails with:

```
Error during login: RequestError ... code: 1013, "Please update"
```

Bumping the `appVersion` string in `authentication.py` does **not** fix
it — the API demands the new verification flow, not a newer version label.

### The fix (until it lands upstream)

The community built a **custom integration** with the email-verification
flow: a patched copy of the HA ecovacs integration that vendors its own
deebot_client. See
[home-assistant/core issue #176484](https://github.com/home-assistant/core/issues/176484)
for the build and install instructions. Summary:

1. Extract the custom integration to `/config/custom_components/ecovacs/`
   (on this setup: `/home/admin/homeassistant/custom_components/ecovacs/`).
2. Re-apply the three GOAT patches to the **vendored** copy — same files,
   new base path: `/config/custom_components/ecovacs/vendor/deebot_client/`
   instead of site-packages inside the container. The vendored library is
   based on deebot-client **18.4.0**; the 18.3.0-based patch files apply
   safely because `cr0e4u.py` and `messages/json/__init__.py` are identical
   in both versions, and the only upstream change in `clean.py`
   (a `cleanings` parameter on `CleanAreaV2`) is a vacuum-only command the
   GOAT never uses.
3. Restart HA. The integration prompts for a verification code sent to
   your Ecovacs account email. Enter it — done.

The custom integration lives in `/config` (a mounted volume), so unlike
the site-packages patches it **survives container updates**. It will be
overwritten if you update the custom integration itself; re-apply the
GOAT patches after any such update.

### ARM / Raspberry Pi: the Rust extension problem

The community build bundles a compiled Rust extension
(`rs.cpython-314-x86_64-linux-musl.so`) — **x86_64 only**. On a Raspberry
Pi (aarch64) the integration fails to load with:

```
ModuleNotFoundError: No module named 'deebot_client.rs.map'
```

`scripts/patch-rs-imports.py` fixes this. It wraps all nine
`deebot_client.rs` import sites in the vendored library with
`try/except ImportError` and installs pure-Python stubs:

```bash
sudo python3 scripts/patch-rs-imports.py
sudo find /home/admin/homeassistant/custom_components/ecovacs/vendor -name '*.pyc' -delete
docker restart home-assistant
```

The script compile-checks every file before writing and is safe to
re-run (already-patched files are skipped).

**Trade-off:** the Rust extension only renders the map image. With the
stubs, HA shows no map picture — mowing control, state, zones, errors,
and all automations are unaffected.

### When the official fix ships

The email-verification flow is being upstreamed. Once a Home Assistant
release includes it: delete `/config/custom_components/ecovacs/`, restart
HA to fall back to the stock integration, and re-apply the three GOAT
patches to site-packages the classic way (`scripts/apply-patches.sh`).

## Surviving container updates

Anything that recreates the container (Watchtower, image update) wipes the
site-packages patches. `scripts/check-patches.sh` checks a sentinel and
reapplies only when needed. It is safe to run hourly: it does nothing (no
restart) when the patches are intact. Root crontab:

```
0 * * * * /home/admin/goat-a3000/scripts/check-patches.sh >> /home/admin/patch.log 2>&1
```

Adjust the path to wherever you cloned the repo.

Note: while running the custom integration (see July 2026 section), the
patched files live in `/config` and survive container updates on their
own — the cron job only matters for the classic site-packages setup.

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
- [home-assistant/core #176484](https://github.com/home-assistant/core/issues/176484)
  tracks the July 2026 auth breakage (error 1013) and the community
  email-verification build.

Once upstream ships native support, delete the cron line and let the
container update normally.

## Credits

- [@reniko](https://github.com/reniko): `CleanMower` command design
  ([PR #1515](https://github.com/DeebotUniverse/client.py/pull/1515))
- [@shinerblue](https://github.com/shinerblue): iOS MQTT captures proving
  `{"type": "auto"}` for all four clean actions
- The contributors on
  [home-assistant/core #176484](https://github.com/home-assistant/core/issues/176484)
  for the email-device-auth custom integration build

## Disclaimer

These patches modify library files inside the HA container at your own
risk. They are version-specific (deebot-client 18.3.0). After a major
library update, diff before reapplying.
