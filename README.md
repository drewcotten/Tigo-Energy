# Tigo Energy

[![GitHub Release](https://img.shields.io/github/v/release/drewcotten/tigo-energy?include_prereleases)](https://github.com/drewcotten/Tigo-Energy/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License](https://img.shields.io/github/license/drewcotten/Tigo-Energy)](LICENSE)

Home Assistant custom integration for **Tigo Energy Premium cloud API** telemetry.

This integration pulls Tigo cloud data into Home Assistant with native UI setup, account login in-flow, and practical handling for cloud-delayed minute telemetry.

In plain terms: you can add your Tigo account, pick one or more systems, and get system, source, array, and panel entities without YAML.

## Documentation

- [Tigo API Integration Notes](docs/tigo-api-integration-notes.md)
- [Tigo Terms Glossary (Home Assistant Mapping)](docs/tigo-terms-glossary-home-assistant.md)
- [Read-Only Alerts Live Probe (2026-03-01)](docs/tigo-readonly-alerts-live-probe-2026-03-01.md)
- [Entity Name Reference (Example IDs)](docs/entity-name-reference.md)
- [Persistent Notifications Reference](docs/persistent-notifications-reference.md)

## Features

- Native Home Assistant onboarding with one account entry and per-system subentries (**Add system** to expand).
- System + source monitoring: power/energy summary plus source heartbeat/control/firmware/gateway state.
- Optional module telemetry (`Pin`, `Vin`, `Iin`, `RSSI`) with semantic panel labels (`A1`, `B4`, etc.).
- Array-level derived sensors (power, voltage/current aggregates, RSSI health, reporting coverage).
- Read-only safety/alert visibility: `PV-Off active`, `String shutdown active`, and alert summary sensors.
- Lag-aware cloud handling (rolling backfill, empty-window fallback, freshness/lag diagnostics).
- Configurable persistent notifications with per-channel toggles (connection, RSSI, telemetry lag, PV-Off, string shutdown, active-alert summary).

## Tigo API Data Time Lag

Tigo cloud data is not strictly real-time. The newest available minute can trail wall-clock time because field uploads and cloud-side processing are asynchronous.

What to expect:

- Minute telemetry is commonly delayed by about 10-20 minutes.
- Delay can be longer during connectivity issues or cloud-side processing slowdowns.
- Short windows can intermittently return empty/minimal data, then appear later.

How this integration handles it:

- Polls with a lag-aware trailing window instead of asking only for "now".
- Uses `recent_cutoff_minutes` as an optional operator control (default `0` = no intentional cutoff).
- Uses rolling backfill (`backfill_window_minutes`) so late-arriving data is picked up.
- Retries once with a wider lookback if short-window results are empty.
- Marks data as stale via attributes/diagnostics when data age exceeds `stale_threshold_seconds`.

In Home Assistant, dashboards show the latest stable cloud value rather than true real-time output. Automations should use freshness/lag context (for example `telemetry_lag_status`, `system_data_is_stale`, and `module_data_is_stale`) instead of assuming current-minute data, and alert thresholds should allow for normal cloud delay before treating missing recent minutes as a fault.

## Latest-State vs Historical Backfill

This integration is a latest-state polling integration. It does not currently import delayed minute buckets into Home Assistant as retroactive historical points.

Practical implication:

- Sensor history reflects when Home Assistant received/accepted updated state, not a full reconstruction of every delayed upstream minute bucket.
- Delayed telemetry still improves current state and lag diagnostics, but older out-of-order buckets may not appear as backfilled chart points.

## Requirements

- Home Assistant `2026.2.0` or newer
- Tigo Premium account/API access
- Internet access from Home Assistant to Tigo cloud API

## Installation

### Manual

1. Open your Home Assistant configuration directory.
2. Create `custom_components/tigo_energy/` if it does not exist.
3. Copy this repository's `custom_components/tigo_energy/` folder into your Home Assistant `custom_components/` directory.
4. Restart Home Assistant.
5. Go to **Settings > Devices & Services > Add Integration**.
6. Search for **Tigo Energy** and start setup.

### HACS custom repository

You can add this repository as a custom integration source in HACS.

## Configuration Flow

The integration setup flow is:

1. Enter Tigo username/password.
2. Integration validates credentials and fetches available systems.
3. Choose initial scope:
   - `single_system` (default) creates one system subentry
   - `all_systems` creates one subentry per discovered system
4. If `single_system`, select the system to add first.
5. Set initial polling intervals in seconds:
   - `summary_poll_seconds` (default `60`)
   - `module_poll_seconds` (default `300`)
6. Choose whether to enable module-level telemetry (`Pin`, `Vin`, `Iin`, `RSSI`). Default is `off`.
7. Choose notification behavior:
   - Master toggle for persistent notifications
   - Per-notification toggles (connection, low RSSI, telemetry lag, PV-Off, string shutdown, active-alert summary)
8. Choose whether to enable sunset-aware guard for RSSI/telemetry-lag alerting. Default is `on`.
9. After setup, use **Add system** on the integration page to add more system subentries under the same account entry.

Tigo API documentation/terms expose rate limiting via `X-Rate-Limit-*` headers and document a per-account cap (`100` requests/minute). Use conservative poll intervals, especially for multi-system accounts.

Reauthentication is supported via Home Assistant UI when credentials/tokens become invalid.
Authentication behavior is internal: bearer tokens are obtained/stored by the integration, proactively renewed when `expires` is available, and retried once on `401` before triggering reauth.

## Options

All options are configurable in **Settings > Devices & Services > Tigo Energy > Configure**:

- `summary_poll_seconds` (default `60`)
- `module_poll_seconds` (default `300`)
- `enable_module_telemetry` (default `false`, also selectable during onboarding)
- `enable_persistent_notifications` (default `true`, master switch)
- `notify_connection_issues` (default `true`)
- `notify_low_rssi` (default `false`)
- `notify_telemetry_lag` (default `false`)
- `notify_pv_off` (default `true`)
- `notify_string_shutdown` (default `true`)
- `notify_active_alert_summary` (default `false`)
- `enable_sunset_alert_guard` (default `true`)
- `sun_guard_min_elevation_degrees` (default `3.0`)
- `sun_guard_positive_power_grace_minutes` (default `90`)
- `stale_threshold_seconds` (default `1800`)
- `backfill_window_minutes` (default `120`)
- `recent_cutoff_minutes` (default `0`)
- `rssi_watch_threshold` (default `120`)
- `rssi_alert_threshold` (default `80`)
- `rssi_alert_consecutive_polls` (default `3`)

## Entities

These are the exact Home Assistant sensor names created by this integration.

Entity footprint planning:

- Module telemetry off: 19 sensors per system when one source is present (14 system-level + 5 source-level), plus 2 system-level binary sensors. Add 5 sensors per additional source.
- Module telemetry on: adds 4 panel sensors per panel (`Pin`, `Vin`, `Iin`, `RSSI`), 3 RSSI aggregate sensors per system, and 15 array sensors per detected array/string.

### System device (`<System Name>`)

- Current power
- Daily energy
- YTD energy
- Lifetime energy
- Latest stable data timestamp
- Telemetry lag
- Heartbeat age
- System status
- Recent alert count
- Has monitored modules
- Active alert count
- Latest alert title
- Latest alert code
- Latest alert time

System entities/devices are created per configured system subentry, including cases where module telemetry is discovered before full summary payloads are available.

### System binary sensors (`<System Name>`)

- PV-Off active
- String shutdown active

### Source device (`<Source Name>`)

- Last check-in
- Control state
- Firmware version
- Gateway count
- Source serial

### Array device (`<System Name> Array <array_label>`, module telemetry enabled)

- Array power
- Array voltage
- Array average voltage (diagnostic)
- Array minimum voltage
- Array maximum voltage
- Array average current
- Array minimum current
- Array maximum current
- Array average RSSI
- Array worst RSSI
- Array low RSSI count
- Array watch RSSI count
- Array module count
- Array reporting module count
- Array reporting coverage

### Panel device (`<System Name> Panel <panel_label>`, opt-in)

- Input power
- Input voltage
- Input current
- RSSI

When available, panel devices/entities use Tigo semantic labels from aggregate key headers (for example `A1`, `B12`, `C3`) and are associated to array devices derived from `/system/layout`. If a semantic label is not present, the integration falls back to module ID-style naming.
For multi-system accounts, panel entities use deterministic system-scoped object IDs to avoid `_2`, `_3` slug collisions when multiple systems have the same panel label.
Panel entities are created from Tigo topology/inventory labels and remain present regardless of time of day; when no recent telemetry point exists (for example overnight), panel sensor values show as unknown until new points arrive.

### Additional system diagnostics (when module telemetry is enabled)

- Low RSSI module count
- Watch RSSI module count
- Worst module RSSI

### RSSI Attributes

RSSI module entities expose additional attributes for easier automation/filtering:

- `rssi_scale` (`0-255`)
- `rssi_watch_threshold`
- `rssi_alert_threshold`
- `rssi_status` (`good`, `watch`, `alert`)

### Telemetry Lag Attributes

Telemetry lag and heartbeat age entities expose additional attributes for lag diagnostics:

- `telemetry_lag_status` (effective status: `ok`, `warning`, `critical`, `suppressed_night`)
- `telemetry_lag_status_raw` (raw threshold status before sunset guard)
- `lag_warning_minutes` (default `20`)
- `lag_critical_minutes` (default `45`)
- `latest_source_checkin`
- `latest_non_empty_telemetry_timestamp`
- `telemetry_lag_guard_active`
- `telemetry_lag_guard_reason`
- `sun_state`
- `sun_elevation`
- `latest_positive_telemetry_timestamp`
- `positive_production_age_minutes`

### Alert Attributes

Alert sensors and alert binary sensors expose:

- `alerts_supported`
- `latest_alert_id`
- `latest_alert_unique_id`
- `latest_alert_message`
- `latest_alert_description_html`
- `latest_alert_archived`

System and module entities also expose freshness context:

- `system_data_timestamp`
- `system_data_age_seconds`
- `system_data_is_stale`
- `module_data_timestamp` (plus backward-compatible `module_latest_timestamp`)
- `module_data_age_seconds`
- `module_data_is_stale`

## Data Freshness and Cloud Lag

Tigo minute data can lag real time because field data and cloud-side processing are not instantaneous.

This integration uses a lag-aware strategy:

- Poll summary/source data at configured cadence
- For module data, query a rolling trailing window
- Optional: set `recent_cutoff_minutes` above `0` if your site/API needs a guard band
- If a short window returns empty telemetry, retry once with a wider lookback and local filter
- Drop future CSV bucket rows more than 5 minutes ahead
- Dedupe repeated/late-arriving points
- Mark data as stale in entity attributes when data age exceeds `stale_threshold_seconds`

Availability behavior:

- Entities stay available during expected cloud lag when coordinator updates are healthy and entity data exists.
- Freshness is represented via lag/stale attributes and diagnostic sensors.
- Alert entities are read-only and remain available even when no active alerts are present (`active_alert_count=0`).

Timestamp handling rules:

- ISO timestamps with offsets are normalized to UTC internally.
- Date-only fields (for example `turn_on_date`) are treated as metadata dates, not freshness instants.
- CSV `Datetime` values without offsets are interpreted as site-local bucket times (`system timezone -> Home Assistant timezone -> UTC`).

## Sunset-Aware Alerting

The integration can suppress data-quality alert escalation at night while keeping telemetry visible:

- Lag status is computed in two forms:
  - Raw (`telemetry_lag_status_raw`) from fixed thresholds.
  - Effective (`telemetry_lag_status`) which can become `suppressed_night` when sunset guard is active.
- Low-RSSI and telemetry-lag persistent notifications honor sunset guard context.
- Connectivity/auth/API failure notifications are never sunset-suppressed.
- PV-Off, string-shutdown, and active-alert summary notifications are read-only alert-feed signals and are not sunset-suppressed.

## Troubleshooting

- **Invalid auth**: verify credentials in Tigo portal and run reauthenticate in integration UI.
- **Cannot connect to Tigo API**: a Home Assistant persistent notification is shown while connectivity is down; it clears automatically once polling recovers.
- **Low RSSI alert**: when `notify_low_rssi` is enabled, a Home Assistant persistent notification appears when low RSSI persists for the configured debounce window (`rssi_alert_consecutive_polls`) and auto-clears when no modules remain below `rssi_alert_threshold`.
- **Telemetry lag alert**: when `notify_telemetry_lag` is enabled, a Home Assistant persistent notification appears when heartbeat-vs-telemetry lag is critical (`>=45m`) for 2 consecutive summary polls and clears when critical lag resolves.
- **No systems found**: confirm account has system access and Premium/API entitlement.
- **Data appears delayed**: expected with cloud lag; tune `backfill_window_minutes` (and optionally `recent_cutoff_minutes` if needed for stability).
- **Module names changed after upgrade**: expected once per install when semantic labels are available; the integration migrates old raw numeric module IDs to label-based IDs (for example `89287797` -> `A1`) in Home Assistant registry.
- **Too many entities**: disable module telemetry or increase module poll interval.

## Development

```bash
pip install -r requirements_dev.txt
ruff check .
pytest -q
```

## License

[MIT](LICENSE)
