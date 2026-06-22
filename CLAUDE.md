# Project Memory — ai-stack / GOAT A3000 HA Integration

## Active work

All Ecovacs GOAT A3000 LiDAR mower work lives in `goat-a3000/`.

### Files

| File | Purpose |
|---|---|
| `goat-a3000/goat_mower_garage.yaml` | HA package — all helpers, scripts, automations |
| `goat-a3000/dashboard.yaml` | Settled HA dashboard card YAML (reference copy) |
| `goat-a3000/validate-patches.sh` | Verifies deebot-client patches are active in container |
| `goat-a3000/README.md` | deebot-client patch docs |

### Hardware

- Mower: GOAT A3000 LiDAR, model `cr0e4u`, firmware 1.13.31
- HA: Docker container `home-assistant` on Raspberry Pi
- deebot-client: 18.3.0
- Soil moisture sensor: `sensor.front_rain_sensor_soil_moisture` (front yard, THIRDREALITY Gen2 Zigbee)
- Additional moisture sensors on dashboard: `sensor.lawn_front_soil_moisture`, `sensor.lawn_back_soil_moisture`

### Zone IDs (cr0e4u)

Confirmed via debug log (`onCleanInfo` → `"type":"spotArea","value":"3,2,6,4,7,5"`):

| ID | Area |
|---|---|
| 2 | Front Street |
| 3 | Front |
| 4 | Left Side Street |
| 5 | Backyard Side |
| 6 | Left Side |
| 7 | Backyard |

Default zone order in `input_text.goat_zone_ids`: `3,2,6,4,7,5`

---

## goat_mower_garage.yaml — current state

### Key design decisions

- **Scheduling**: HA is the sole scheduler. All Ecovacs app schedules deleted.
  `GOAT - Scheduled Start Gatekeeper` fires at `input_datetime.goat_mowing_start_time`
  and checks `input_boolean.goat_schedule_{mon..sun}` for the current day.

- **Mow mode**: Both scheduled (`goat_mowing_start`) and manual (`goat_start_mowing_now`)
  and makeup (`GOAT - Makeup Day Check`) read `input_select.goat_mow_mode` and
  `input_text.goat_zone_ids`. All three paths write the zone file and call
  `lawn_mower.start_mowing` directly.

- **Wet grass detection**: `sensor.front_rain_sensor_soil_moisture >= 55%` blocks mowing.
  Physical sensor catches rain, dew, and drizzle. Threshold: 55%.

- **Rain forecast**: PirateWeather 95-minute window. Blocks if `precipitation_probability >= 40%`
  or condition in `['rainy','pouring','lightning','lightning-rainy']`.

- **Makeup mowing**: When a scheduled mow is weather-cancelled, `goat_makeup_pending` turns on.
  `GOAT - Makeup Day Check` retries hourly 11am–7pm on non-scheduled days. Sends one
  notification at 11am if still blocked; silent retries each hour after. Clears on any
  successful dock.

- **Critical notifications**: Only errors and "not docked after 2 hours" use `critical: true`.
  All other notifications are non-critical.

- **Manual Start Detected**: Fires on every `mowing` state transition where
  `goat_mowing_session_active = off`. Checks weather; if rain forecast → docks and notifies.
  If clear → opens garage, sets session active (authorizes the run).

### Entities

**input_boolean**
- `goat_automation_enabled` — master on/off
- `goat_garage_managed_open` — tracks whether HA opened the garage
- `goat_departure_window_active` — garage open, mower hasn't left yet
- `goat_mowing_session_active` — HA-authorized mowing session in progress
- `goat_schedule_mon` … `goat_schedule_sun` — scheduled mowing days
- `goat_makeup_pending` — a scheduled mow was cancelled; makeup needed

**input_datetime**
- `goat_mowing_start_time` — daily scheduled start time (time only)
- `goat_mowing_session_started_at` — timestamp of session start (used for +95min return window)
- `goat_last_mowing_decision` — timestamp of last go/cancel decision

**input_text**
- `goat_last_mowing_status` — "Normal" | "Manual" | "Makeup" | "Returning" | "Cancelled due to weather"
- `goat_zone_ids` — comma-separated zone IDs, default `3,2,6,4,7,5`

**input_select**
- `goat_mow_mode` — "Areas (e.g., 3,2,6,4,7,5)" | "Full Map (Auto)"

**shell_command**
- `goat_write_zones` — writes `input_text.goat_zone_ids` to `/tmp/goat_zones` inside container

### Scripts

| Script | Purpose |
|---|---|
| `goat_notify` | Send iOS push; `critical: true` for DND-bypassing alerts |
| `goat_open_garage` | Open + wait for confirmation; sets `goat_garage_managed_open` |
| `goat_close_garage` | Close only if `goat_garage_managed_open = on` |
| `goat_try_dock` | Send dock command twice (20s apart) |
| `goat_mowing_start` | Scheduled mow: weather check → zone write → open garage → start_mowing |
| `goat_start_mowing_now` | Manual mow: same flow, explicit `lawn_mower.start_mowing` |
| `goat_test_weather_check` | Debug: runs forecast + soil moisture check, posts persistent notification |

### Automations

| Automation | Trigger | Purpose |
|---|---|---|
| GOAT - Scheduled Start Gatekeeper | Time matches `goat_mowing_start_time` | Calls `goat_mowing_start` on scheduled days |
| GOAT - Makeup Day Check | Hourly 11am–7pm | Starts makeup mow when conditions clear on non-scheduled days |
| GOAT - Manual Start Detected | Mower → mowing (session_active = off) | Weather check; dock if rain, authorize if clear |
| GOAT - Close Garage When Mowing Starts | Mower → mowing (departure_window = on) | Close garage 1 min after departure |
| GOAT - Open Garage When Returning | Mower → returning (session_active = on) | Open garage for return |
| GOAT - Close Garage When Docked | Mower → docked (session_active = on) | Close garage, clear session + makeup flags |
| GOAT - Paused Too Long Return To Dock | Paused > 5 min (session_active = on) | Critical alert + dock |
| GOAT - Error After Mowing Started | Error sensor ≠ 0 (session_active = on) | Critical alert + open garage + dock |
| GOAT - Open Garage For Expected Return | start_time + 95 min | Preemptive garage open (backup for returning signal) |
| GOAT - Not Docked Fallback Alert | start_time + 120 min (not docked) | Critical alert if mower still out after 2 hours |

---

## Dashboard — settled layout (Jun 2026)

Three cards in a vertical-stack:

1. **Entities card** — GOAT status + Scheduled Mowing (start time, mow mode, zone IDs)
2. **7-column button grid** (`custom:button-card`) — Mon–Sun day selectors, green=on/grey=off
3. **Entities card** titled "Mowing Run" — Manual Mowing (Start Now button) + Session Status rows

Full card YAML in `goat-a3000/dashboard.yaml`.

HACS cards required: `custom:button-card`, `custom:template-entity-row`
