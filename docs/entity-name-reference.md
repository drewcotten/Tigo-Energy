# Entity Name Reference (Example: System `6251 S Adams`)

This reference shows expected Home Assistant display names and first-install entity IDs for one example system.

- System name: `6251 S Adams`
- System ID: `174596`
- Source name: `Primary CCA`
- Panel labels shown: `A1`, `A2`, `A3` (sample subset)

Notes:

- Entity IDs can differ if an ID already exists in your HA registry (HA appends suffixes like `_2`).
- Panel entities now use deterministic system-scoped object IDs to avoid cross-system collisions.

## System Sensors

- Current power -> `sensor.6251_s_adams_current_power`
- Daily energy -> `sensor.6251_s_adams_daily_energy`
- YTD energy -> `sensor.6251_s_adams_ytd_energy`
- Lifetime energy -> `sensor.6251_s_adams_lifetime_energy`
- Latest stable data timestamp -> `sensor.6251_s_adams_latest_stable_data_timestamp`
- Telemetry lag -> `sensor.6251_s_adams_telemetry_lag`
- Heartbeat age -> `sensor.6251_s_adams_heartbeat_age`
- System status -> `sensor.6251_s_adams_system_status`
- Recent alert count -> `sensor.6251_s_adams_recent_alert_count`
- Has monitored modules -> `sensor.6251_s_adams_has_monitored_modules`
- Active alert count -> `sensor.6251_s_adams_active_alert_count`
- Latest alert title -> `sensor.6251_s_adams_latest_alert_title`
- Latest alert code -> `sensor.6251_s_adams_latest_alert_code`
- Latest alert time -> `sensor.6251_s_adams_latest_alert_time`

## Source Sensors (`Primary CCA`)

- Last check-in -> `sensor.primary_cca_last_check_in`
- Control state -> `sensor.primary_cca_control_state`
- Firmware version -> `sensor.primary_cca_firmware_version`
- Gateway count -> `sensor.primary_cca_gateway_count`
- Source serial -> `sensor.primary_cca_source_serial`

## System Binary Sensors

- PV-Off active -> `binary_sensor.6251_s_adams_pv_off_active`
- String shutdown active -> `binary_sensor.6251_s_adams_string_shutdown_active`

## Panel Sensors (sample)

### `6251 S Adams Panel A1`

- Input power -> `sensor.system_174596_panel_a1_pin`
- Input voltage -> `sensor.system_174596_panel_a1_vin`
- Input current -> `sensor.system_174596_panel_a1_iin`
- RSSI -> `sensor.system_174596_panel_a1_rssi`

### `6251 S Adams Panel A2`

- Input power -> `sensor.system_174596_panel_a2_pin`
- Input voltage -> `sensor.system_174596_panel_a2_vin`
- Input current -> `sensor.system_174596_panel_a2_iin`
- RSSI -> `sensor.system_174596_panel_a2_rssi`

### `6251 S Adams Panel A3`

- Input power -> `sensor.system_174596_panel_a3_pin`
- Input voltage -> `sensor.system_174596_panel_a3_vin`
- Input current -> `sensor.system_174596_panel_a3_iin`
- RSSI -> `sensor.system_174596_panel_a3_rssi`

## RSSI Aggregate Sensors (module telemetry enabled)

- Low RSSI module count -> `sensor.6251_s_adams_low_rssi_module_count`
- Watch RSSI module count -> `sensor.6251_s_adams_watch_rssi_module_count`
- Worst module RSSI -> `sensor.6251_s_adams_worst_module_rssi`
