# Entity Name Reference (Example: `System_Name`)

This reference maps what users see in Home Assistant to example entity IDs.

- Example system display name: `System_Name`
- Example source display name: `Primary CCA`
- Example array display name: `Array A`
- Example panel labels: `A1`, `A2`, `A3`

## Telemetry Scope Matrix

- Array telemetry `on` + panel telemetry `off` (default): system + source + array + RSSI aggregate entities.
- Array telemetry `on` + panel telemetry `on`: everything above, plus per-panel entities.
- Array telemetry `off` + panel telemetry `on`: system + source + per-panel entities only.
- Array telemetry `off` + panel telemetry `off`: system + source entities only.

## Naming Rules

- Display names are user-facing labels (system/source/array/panel names).
- Entity IDs (`sensor.xxx`, `binary_sensor.xxx`) are slugified by Home Assistant.
- Panel and array suggested object IDs are system-scoped to avoid cross-system collisions.
- If an entity ID already exists in registry, Home Assistant appends suffixes (`_2`, `_3`, etc.).

Panel entity ID pattern:
- `sensor.system_<system_id>_panel_<panel_label>_<metric>`

Array entity ID pattern:
- `sensor.system_<system_id>_array_<array_id>_<metric>`

Array ID note:
- `<array_id>` comes from topology metadata and is often `string_<string_id>`, for example `string_57810`.

## System Sensors

- Current power -> `sensor.system_name_current_power`
- Daily energy -> `sensor.system_name_daily_energy`
- YTD energy -> `sensor.system_name_ytd_energy`
- Lifetime energy -> `sensor.system_name_lifetime_energy`
- Latest stable data timestamp -> `sensor.system_name_latest_stable_data_timestamp`
- Telemetry lag -> `sensor.system_name_telemetry_lag`
- Heartbeat age -> `sensor.system_name_heartbeat_age`
- System status -> `sensor.system_name_system_status`
- Recent alert count -> `sensor.system_name_recent_alert_count`
- Has monitored modules -> `sensor.system_name_has_monitored_modules`
- Active alert count -> `sensor.system_name_active_alert_count`
- Latest alert title -> `sensor.system_name_latest_alert_title`
- Latest alert code -> `sensor.system_name_latest_alert_code`
- Latest alert time -> `sensor.system_name_latest_alert_time`

## Source Sensors (`Primary CCA`)

- Last check-in -> `sensor.primary_cca_last_check_in`
- Control state -> `sensor.primary_cca_control_state`
- Firmware version -> `sensor.primary_cca_firmware_version`
- Gateway count -> `sensor.primary_cca_gateway_count`
- Source serial -> `sensor.primary_cca_source_serial`

## System Binary Sensors

- PV-Off active -> `binary_sensor.system_name_pv_off_active`
- String shutdown active -> `binary_sensor.system_name_string_shutdown_active`

## Array Sensors (sample, `enable_array_telemetry=true`)

### `System_Name Array A`

- Array power -> `sensor.system_<system_id>_array_string_57810_array_power`
- Array voltage -> `sensor.system_<system_id>_array_string_57810_array_voltage`
- Array average voltage (diagnostic) -> `sensor.system_<system_id>_array_string_57810_array_voltage_average`
- Array minimum voltage -> `sensor.system_<system_id>_array_string_57810_array_voltage_min`
- Array maximum voltage -> `sensor.system_<system_id>_array_string_57810_array_voltage_max`
- Array average current -> `sensor.system_<system_id>_array_string_57810_array_current_average`
- Array minimum current -> `sensor.system_<system_id>_array_string_57810_array_current_min`
- Array maximum current -> `sensor.system_<system_id>_array_string_57810_array_current_max`
- Array average RSSI -> `sensor.system_<system_id>_array_string_57810_array_rssi_average`
- Array worst RSSI -> `sensor.system_<system_id>_array_string_57810_array_rssi_worst`
- Array low RSSI count -> `sensor.system_<system_id>_array_string_57810_array_rssi_low_count`
- Array watch RSSI count -> `sensor.system_<system_id>_array_string_57810_array_rssi_watch_count`
- Array module count -> `sensor.system_<system_id>_array_string_57810_array_module_count`
- Array reporting module count -> `sensor.system_<system_id>_array_string_57810_array_reporting_module_count`
- Array reporting coverage -> `sensor.system_<system_id>_array_string_57810_array_reporting_coverage`
- Array latest stable panel data timestamp -> `sensor.system_<system_id>_array_string_57810_array_latest_stable_panel_data_timestamp`
- Array telemetry lag -> `sensor.system_<system_id>_array_string_57810_array_telemetry_lag_minutes`

## Panel Sensors (sample, `enable_panel_telemetry=true`)

### `System_Name Panel A1`

- Input power -> `sensor.system_<system_id>_panel_a1_pin`
- Input voltage -> `sensor.system_<system_id>_panel_a1_vin`
- Input current -> `sensor.system_<system_id>_panel_a1_iin`
- RSSI -> `sensor.system_<system_id>_panel_a1_rssi`

### `System_Name Panel A2`

- Input power -> `sensor.system_<system_id>_panel_a2_pin`
- Input voltage -> `sensor.system_<system_id>_panel_a2_vin`
- Input current -> `sensor.system_<system_id>_panel_a2_iin`
- RSSI -> `sensor.system_<system_id>_panel_a2_rssi`

### `System_Name Panel A3`

- Input power -> `sensor.system_<system_id>_panel_a3_pin`
- Input voltage -> `sensor.system_<system_id>_panel_a3_vin`
- Input current -> `sensor.system_<system_id>_panel_a3_iin`
- RSSI -> `sensor.system_<system_id>_panel_a3_rssi`

Panel attributes:

- `module_id`: semantic panel label (for example `A1`)
- `raw_module_id`: raw object/module-style ID when available
- `array_id`: mapped array identifier for that panel
- `array_name`: mapped array display name for that panel

## RSSI Aggregate Sensors (`enable_array_telemetry=true`)

- Low RSSI module count -> `sensor.system_name_low_rssi_module_count`
- Watch RSSI module count -> `sensor.system_name_watch_rssi_module_count`
- Worst module RSSI -> `sensor.system_name_worst_module_rssi`
