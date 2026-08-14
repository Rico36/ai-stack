## HA Component Stack

### Host environment

Home Assistant runs as a **Docker container** (`home-assistant`) on a **Raspberry Pi**
running Raspberry Pi OS 64-bit. The container name and Python site-packages path are
referenced in `validate-patches.sh` — adjust them if your setup differs.

### Integrations (installed via Settings → Integrations)

| Integration | Purpose | Entity used |
|---|---|---|
| Ecovacs (with deebot-client patches) | Mower control and state | `lawn_mower.goat_a3000_lidar` |
| PirateWeather | Hourly rain forecast for 95-minute window | `weather.pirateweather` |
| iOS Companion App | Push notifications (critical + regular) | `notify.house_phones` |
| Alexa Media Player | Spoken pre-mow reminders | `notify.house_alexas` |
| Zigbee (ZHA or Zigbee2MQTT) | Connects the soil moisture sensor | — |
| ESPHome — [Ratgdo32](https://ratcloud.llc/products/ratgdo32) | Garage door open/close control and state | `cover.garage_door` |

> **Ratgdo32** is a Wi-Fi garage door controller that integrates with HA via ESPHome.
> It wires directly to the garage door opener's safety terminals — no cloud required.
> Any HA `cover` entity works as a drop-in replacement; update `cover.garage_door`
> references in `goat_mower_garage.yaml` to match your entity name.

> The Ecovacs integration requires the deebot-client patches in the `/patches` folder to
> work correctly with the A3000. See the repo root README for install instructions —
> including the July 2026 auth change (error 1013) and custom-integration setup.

### HACS frontend cards (required for the dashboard)

| Card | Purpose |
|---|---|
| `custom:button-card` | Day-of-week selector grid (green = scheduled, grey = off) |
| `custom:template-entity-row` | Formatted session status rows (Expected Return, Last Decision, etc.) |

Install both from HACS → Frontend before pasting the dashboard YAML.

### Built-in HA platforms used

| Platform | Purpose |
|---|---|
| `sensor: platform: statistics` | 30-minute rolling **minimum** of soil moisture (`sensor.soil_moisture_30min_min`) — feeds the delta-spike rule |
| `input_select` | Grass Status (Uncertain / Dry / Wet) and Mow Mode |
| `input_boolean` | Session flags, schedule day toggles, garage tracking, override + delta flags |
| `input_number` | Dry baseline (`goat_moisture_baseline`) — the moisture level known to be dry |
| `input_datetime` | Scheduled start time, session timestamps, override start time |
| `input_text` | Zone IDs, last mowing status label |
| `shell_command` | Writes zone IDs to `/tmp/goat_zones` inside the HA container |

External sensor referenced by the pre-mow reminders (define it to match your
setup, or remove the check): `sensor.goat_rain_last_3_hours` — accumulated
rain over the past 3 hours.

---

## Soil Moisture Sensor

**THIRDREALITY Smart Soil Moisture Sensor Gen2 (Zigbee)**
[Amazon listing](https://www.amazon.com/dp/B0GHNB78F7/ref=twister_B0GN8TYSFF?_encoding=UTF8&psc=1)

Stake it into the lawn in the front yard (or wherever representative of the mowing area).
Pairs via ZHA or Zigbee2MQTT. Once paired, rename the moisture entity to:

```
sensor.front_rain_sensor_soil_moisture
```

or update the entity ID references in `goat_mower_garage.yaml` to match your actual name.

---

## Grass Status — automatic classification

`input_select.goat_grass_status` (Uncertain / Dry / Wet) is the primary mowing
gate. The automation `GOAT - Update Grass Status` re-evaluates it on every
soil moisture change, using a strict **priority chain** — the first rule that
matches wins:

| # | Rule | Condition | Result |
|---|---|---|---|
| P1 | Floor dry | moisture < 55% AND not morning (4–10 AM) | **Dry** — clears delta + override; baseline untouched |
| P2 | Delta spike | status was Dry AND moisture rose > 3% above its 30-min minimum | **Wet** — sets delta flag, stores the 30-min minimum as the dry baseline; the only rule that overrides a manual override |
| P3 | Manual override hold | override flag on (and not expired) | status held as-is |
| P4 | Delta cancellation | delta flag on AND moisture ≤ dry baseline **+ 1** | **Dry** — clears delta flag, stores the settled value as the new baseline |
| P5 | Delta hold | delta flag on, moisture still above the baseline | held **Wet** |
| P6 | Morning dew | 4–10 AM AND moisture > 51% | **Wet** — unconditional; morning and delta are the two rules that override the baseline |
| P7 | High moisture | moisture > 79% AND above the dry baseline | **Wet** |
| P8 | Normal dry | moisture ≤ dry baseline | **Dry** |

If no rule matches, the last status holds ("Uncertain" if never set).

### The dry baseline (`goat_moisture_baseline`)

The "dry baseline" is the moisture level known to be dry — **69%** by
default (when the helper is 0/unset). It is never reset on a schedule,
never set from an unvalidated reading, and only delta and morning outrank
it. It changes three ways:

- **Manual Dry** from the dashboard saves the current soil moisture as the
  baseline. Example: you set Dry at 76% → any reading ≤ 76% counts as Dry
  outside the morning window.
- **Delta scenarios** maintain it automatically: a spike stores the 30-min
  pre-rain minimum; a cancellation stores the settled value.
- **Manual Wet** clears it back to 0 (threshold falls back to 69).

Recovery from a Wet morning happens through the validated rules alone:
once the morning window ends, floor dry (< 55%), normal dry (≤ baseline),
or a delta cancellation flips the status back to Dry as the dew
evaporates. On humid days where moisture plateaus **above** the baseline,
the status deliberately stays Wet — setting Dry manually both unblocks
the day and recalibrates the baseline to the observed humid-climate
level, so the system learns from you rather than guessing.

### Manual overrides

Changing Grass Status from the dashboard dropdown sets an override flag
(`GOAT - Lock Grass Status On Manual Override` — it detects a human user
in the state-change context, so automation-driven changes don't lock):

- The override **holds the status** against all automatic rules except the
  delta spike (P2), which represents actual rain landing on the sensor.
- It **auto-expires after 5 hours** (`GOAT - Expire Manual Override`).
- Manual **Dry** also records the dry threshold (above); manual **Wet**
  clears it.

Thresholds are starting points — calibrate over a few rain/dry cycles by
watching the sensor history chart.

---

## Mowing decision gates

Every mow attempt (scheduled, manual, makeup) must pass **all** of these
gates, evaluated in the mow scripts immediately before starting:

| Gate | Blocks if... |
|---|---|
| Mower error | error sensor ≠ 0 |
| Grass Status | `Wet` blocks; `Dry` passes; `Uncertain` falls back to raw soil moisture ≥ 55% |
| Rain forecast | PirateWeather: precipitation probability ≥ 40% **or** condition in rainy / pouring / lightning / lightning-rainy, in the next 95 minutes |

A manual **Dry** override passes the Grass Status gate — the user accepts
responsibility if conditions turn out otherwise. The forecast and error
gates are never bypassed.

---

## Pre-mow reminders (scheduled days only)

Two reminder automations fire before the scheduled start time, on days
enabled via the dashboard day toggles (same source of truth as the
gatekeeper) and only while `goat_automation_enabled` is on. Both run the
same pre-check: Grass Status Wet, rain in the past 3 hours
(`sensor.goat_rain_last_3_hours`), mower error, or rain forecast in the
95 minutes after the scheduled start.

| Automation | When | If blocked | If clear |
|---|---|---|---|
| `GOAT - Mower Garage Reminder` | T−17 min | Phone push: "Robot Mower Kept Inside" + reason | Alexa announcement: set up the mower, remove the sensor cover, open the backyard gate |
| `GOAT - Garage Door Reminder` | T−5 min | **Critical** phone push: "GOAT Kept Inside" + reason | Alexa announcement: garage opens automatically in 5 minutes |

These are advisory — the authoritative go/no-go decision still happens in
`goat_mowing_start` at start time (conditions can change in 17 minutes).

---

## Scenario 1 — Manual mowing (Press "Start Mowing Now" in the HA dashboard)

1. **Button** calls `script.goat_start_mowing_now`
2. **goat_start_mowing_now** — 5s delay → refresh entity state → weather check
   - If Grass Status = Wet, or (Uncertain + soil moisture ≥ 55%), or rain forecast in next 95 min, or mower error → cancel, notify, done
   - If clear:
     - If mode = **Areas** → `shell_command.goat_write_zones` writes zone IDs to `/tmp/goat_zones`
     - Turns on `goat_departure_window_active` + `goat_mowing_session_active`
     - Records `goat_mowing_session_started_at`
     - Calls `goat_open_garage` (opens door, waits up to 1 min, sets `goat_garage_managed_open`)
     - Calls `lawn_mower.start_mowing` → CleanMowerArea reads zone file (or falls back to auto)
     - Notifies (regular)
3. **Mower → mowing**
   - `GOAT - Close Garage When Mowing Starts` fires (because `departure_window_active` = on) → waits 1 min → closes garage → turns off `departure_window_active`
   - `GOAT - Departure Handler` does **not** fire — `departure_window_active` was on at the transition, condition fails
4. **Mower → returning** — `GOAT - Open Garage When Returning` fires → opens garage, sets status "Returning", notifies (regular)
5. **Mower → docked** — `GOAT - Close Garage When Docked` fires → waits 1 min → closes garage, then checks the workComplete marker (see "Mid-run recharge" below): run complete → turns off `mowing_session_active` + `goat_makeup_pending`, notifies (regular); no marker → recharge break, session stays active
6. **At session_started_at + 120 min** (fallback) — `GOAT - Not Docked Fallback Alert` fires only if still not docked → **critical** notify

**If anything goes wrong mid-session:**
- Error reported → `GOAT - Error After Mowing Started` → opens garage + tries dock → **critical** notify
- Paused 5+ min → `GOAT - Paused Too Long Return To Dock` → docks → **critical** notify

---

## Scenario 2 — Scheduled mowing (HA is the sole scheduler; Ecovacs app schedules deleted)

1. **`GOAT - Scheduled Start Gatekeeper`** fires every minute via `time_pattern`, checks if
   `now()` matches `input_datetime.goat_mowing_start_time`
   - Condition: `goat_automation_enabled` = on AND today's `goat_schedule_<weekday>` toggle = on
   - Days are set from the dashboard — 7 green/grey buttons (Mon–Sun), tap to toggle
2. Calls `script.goat_mowing_start`
3. **goat_mowing_start** — 10s delay → refresh state → weather + Grass Status check
   - If blocked: Cancel, set `goat_makeup_pending` = on, notify "Mowing cancelled — makeup pending" (regular)
   - If clear:
     - If mode = **Areas** → `shell_command.goat_write_zones` writes zone IDs to `/tmp/goat_zones`
     - Turns on `goat_departure_window_active` + `goat_mowing_session_active`
     - Records `goat_mowing_session_started_at`
     - Calls `goat_open_garage`
     - Calls `lawn_mower.start_mowing` → mower starts immediately (no Ecovacs schedule needed)
     - Notifies "Scheduled mowing started" (regular)
4. **Mower → mowing**
   - `GOAT - Departure Handler` does **not** fire — `departure_window_active` is on
   - `GOAT - Close Garage When Mowing Starts` fires → waits 1 min → closes garage
5. Steps 4–6 from Scenario 1 apply identically from here

**Unauthorized start or recharge resume** (any `docked → mowing` transition HA
did not initiate — app start, physical button, or the mower resuming a
mid-run recharge on its own):
- `GOAT - Departure Handler` fires (condition: `departure_window_active` = off)
- **Pauses the mower immediately** (so it can't race HA to a closed garage
  door), then checks the rain forecast
- Rain forecast → docks + **critical** notify "Mower stopped due to weather"
- Clear → authorizes the session, stamps the session clock (re-arming the
  95-min and 2-hour windows after a recharge), opens the garage, resumes
  (start_mowing converts to RESUME while paused), notifies, closes the
  garage after 1 min

**Mid-run recharge** (low battery, mower docks to charge, then resumes):
- The mower only emits `workComplete` when a run truly finishes (~2 min
  before the final dock). The patched vendored `clean.py` writes
  `/tmp/goat_work_complete` when it sees it, and
  `shell_command.goat_check_work_complete` reports whether the marker is
  fresh (< 20 min). Battery level is deliberately not used — runs have
  been observed completing at 17%.
- Dock **with** a fresh marker → run complete: session closed, "Mower
  docked" notification
- Dock **without** a marker → recharge break: garage closes, session
  stays active, "Mower recharging" notification; when the mower resumes,
  the Departure Handler reopens the garage
- Safety net: `GOAT - Session Cleanup After Long Charge` closes out any
  session still active after 3 hours docked

---

## Scenario 3 — Makeup mowing (auto-retry after a weather cancellation)

Triggered when a scheduled mow was cancelled and `goat_makeup_pending` = on.

1. **`GOAT - Makeup Day Check`** fires every hour on the hour, 11am–7pm
   - Conditions: `goat_automation_enabled` = on, `goat_makeup_pending` = on,
     `mowing_session_active` = off, today is **not** a scheduled mowing day
     (scheduled days run via the gatekeeper; makeup only fills non-scheduled gaps)
2. Weather + Grass Status check — same conditions as scheduled mow
   - If still blocked and time is 11am → notify "Makeup mow waiting, will retry hourly" (regular); silent retries each hour after
   - If clear:
     - If mode = **Areas** → writes zone file
     - Turns on `goat_departure_window_active` + `goat_mowing_session_active`
     - Records `goat_mowing_session_started_at`
     - Calls `goat_open_garage`
     - Calls `lawn_mower.start_mowing`
     - Notifies "Makeup mow started" (regular)
3. From here, steps 4–6 from Scenario 1 apply — including clearing `goat_makeup_pending` on dock

**`goat_makeup_pending` lifecycle:**
- Set on: scheduled mow cancelled by weather or Grass Status
- Cleared: any mowing session ends with mower docked (`GOAT - Close Garage When Docked`)
- Also manually toggleable from the dashboard

---

## Weather protection (all scenarios)

Two independent blocking checks run before every mow:

| Check | Source | Block threshold |
|---|---|---|
| Wet grass | `input_select.goat_grass_status` + `sensor.front_rain_sensor_soil_moisture` | Status = Wet, or Uncertain + moisture ≥ 55% |
| Rain forecast | PirateWeather (`weather.pirateweather`), next 95 min | precipitation_probability ≥ 40% or condition in rainy/pouring/lightning |

Use `script.goat_test_weather_check` (Developer Tools → Actions) to run a live check — result appears as a persistent notification showing Grass Status, soil moisture, forecast slots, and the go/cancel decision.

---

## Dashboard layout

![Dashboard](dashboard_screenshot.png)

Three sections in a vertical-stack:

1. **Entities card** (title: GOAT Mowing Schedule)
   - GOAT Automation Enabled toggle
   - GOAT Status
   - *Scheduled Auto-Mowing* section: Start Time · Mow Mode · Zone IDs

2. **7-column button grid** (`custom:button-card`) — Mon Tue Wed Thu Fri Sat Sun
   - Green = scheduled, grey = off; tap to toggle

3. **Entities card** (title: Manual Run / Mowing Status)
   - *Manual Mowing* section: Start Mowing Now button
   - *Grass Condition* section: Grass Status (editable dropdown) · Grass Moisture +/- · Soil Moisture · Front Soil Moisture · Back Soil Moisture
   - *Session Status* section: Departure Window Active · Mowing Session Active · Makeup Mow Pending · Last Mowing Started · Last Decision

HACS cards required: `custom:button-card`, `custom:template-entity-row`

Full card YAML in `HA/dashboard.yaml`.
