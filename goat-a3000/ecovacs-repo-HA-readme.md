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
| `input_number` | Moisture baseline (delta rule) and last-dry threshold (`goat_last_dry_m`) |
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
| P1 | Floor dry | moisture < 55% AND not morning (4–10 AM) | **Dry** — clears delta + override, resets baseline |
| P2 | Delta spike | status was Dry AND moisture rose > 6% above its 30-min minimum | **Wet** — sets delta flag; the only rule that overrides a manual override |
| P3 | Manual override hold | override flag on (and not expired) | status held as-is |
| P4 | Delta cancellation | delta flag on AND moisture ≤ dry threshold | **Dry** — clears delta flag |
| P5 | Delta hold | delta flag on, moisture still above dry threshold | held **Wet** |
| P6 | Morning dew | 4–10 AM AND moisture > 51% | **Wet** |
| P7 | High moisture | moisture > 79% | **Wet** |
| P8 | Normal dry | moisture ≤ dry threshold | **Dry** |

If no rule matches, the last status holds ("Uncertain" if never set).

### The dynamic dry threshold (`goat_last_dry_m`)

The "dry threshold" used by P4 and P8 is **69%** by default, but adapts to
your judgment:

- When you **manually set Dry** from the dashboard, the current soil moisture
  is saved to `input_number.goat_last_dry_m` and becomes the new dry
  threshold. Example: you set Dry at 76% → later, any reading ≤ 76% counts
  as Dry, even though the fixed threshold would have said Wet.
- The saved threshold is **reset to 0** (falling back to 69) by a **manual
  Wet** override and every morning at **4 AM** (`GOAT - Reset Dry Threshold
  At Morning`), so morning dew is always judged against the conservative
  fixed threshold.

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
   - `GOAT - Manual Start Detected` does **not** fire — `mowing_session_active` is already on, condition fails
4. **Mower → returning** — `GOAT - Open Garage When Returning` fires → opens garage, sets status "Returning", notifies (regular)
5. **Mower → docked** — `GOAT - Close Garage When Docked` fires → waits 1 min → closes garage → turns off `mowing_session_active` + `goat_makeup_pending`, notifies (regular)
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
   - `GOAT - Manual Start Detected` does **not** fire — `mowing_session_active` is already on
   - `GOAT - Close Garage When Mowing Starts` fires → waits 1 min → closes garage
5. Steps 4–6 from Scenario 1 apply identically from here

**Unauthorized start** (mower starts via physical button or any path outside HA):
- `GOAT - Manual Start Detected` fires (condition: `mowing_session_active` = off)
- Checks weather → if rain forecast → docks + **critical** notify "Mower stopped due to weather"
- If clear → opens garage, sets `mowing_session_active` on, notifies (regular), closes garage after 1 min

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
