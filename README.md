# Tigo Energy

[![GitHub Release](https://img.shields.io/github/v/release/drewcotten/tigo-energy?include_prereleases)](https://github.com/drewcotten/Tigo-Energy/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License](https://img.shields.io/github/license/drewcotten/Tigo-Energy)](LICENSE)

Home Assistant custom integration for **Tigo Energy Premium cloud API** telemetry.

This integration supports native UI onboarding (Config Flow), in-flow authentication, and lag-aware telemetry handling for Tigo cloud data.

## Documentation

- [Tigo API Integration Notes](docs/tigo-api-integration-notes.md)
- [Time-Lag Investigation Report](docs/tigo-integration-time-lag-investigation.md)
- [Tigo Terms Glossary (Home Assistant Mapping)](docs/tigo-terms-glossary-home-assistant.md)
- [Read-Only Alerts Live Probe (2026-03-01)](docs/tigo-readonly-alerts-live-probe-2026-03-01.md)
- [Entity Name Reference (Example IDs)](docs/entity-name-reference.md)

## Features

- Native Home Assistant onboarding with one account entry and per-system subentries (use **Add system** to expand grouped systems under one integration).
- Optional module telemetry from minute aggregate data: per-module input power, voltage, current, and RSSI (`Pin`, `Vin`, `Iin`, `RSSI`), plus system-level RSSI aggregate sensors.
- System and source monitoring: power/energy summary sensors plus source health sensors (check-in, control state, firmware, gateway count, serial).
- Read-only alert and safety monitoring: alert sensors plus `PV-Off active` and `String shutdown active` binary sensors.
- Lag-aware cloud handling: rolling backfill, short-window fallback retry, and freshness diagnostics (`telemetry_lag_status`, stale attributes).
- Semantic panel labeling from Tigo object/layout labels (`A1`, `B4`, etc.) for cleaner device naming.
- Persistent Home Assistant notifications for connectivity, sustained low RSSI, and critical telemetry lag (auto-clear on recovery).

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
7. Choose whether Home Assistant should show persistent warning notifications (connection issues, sustained low RSSI, and critical telemetry lag). Default is `on`.
8. After setup, use **Add system** on the integration page to add more system subentries under the same account entry.

Tigo API documentation/terms expose rate limiting via `X-Rate-Limit-*` headers and document a per-account cap (`100` requests/minute). Use conservative poll intervals, especially for multi-system accounts.

Reauthentication is supported via Home Assistant UI when credentials/tokens become invalid.
Authentication behavior is internal: bearer tokens are obtained/stored by the integration, proactively renewed when `expires` is available, and retried once on `401` before triggering reauth.

## Options

All options are configurable in **Settings > Devices & Services > Tigo Energy > Configure**:

- `summary_poll_seconds` (default `60`)
- `module_poll_seconds` (default `300`)
- `enable_module_telemetry` (default `false`, also selectable during onboarding)
- `enable_persistent_notifications` (default `true`, also selectable during onboarding)
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
- Module telemetry on: adds 4 panel sensors per panel (`Pin`, `Vin`, `Iin`, `RSSI`) plus 3 RSSI aggregate sensors per system.

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

### Panel device (`<System Name> Panel <panel_label>`, opt-in)

- Input power
- Input voltage
- Input current
- RSSI

When available, panel devices/entities use Tigo semantic labels from aggregate key headers (for example `A1`, `B12`, `C3`). If a semantic label is not present, the integration falls back to module ID-style naming.
For multi-system accounts, panel entities use deterministic system-scoped object IDs to avoid `_2`, `_3` slug collisions when multiple systems have the same panel label.

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

- `telemetry_lag_status` (`ok`, `warning`, `critical`)
- `lag_warning_minutes` (default `20`)
- `lag_critical_minutes` (default `45`)
- `latest_source_checkin`
- `latest_non_empty_telemetry_timestamp`

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

## Troubleshooting

- **Invalid auth**: verify credentials in Tigo portal and run reauthenticate in integration UI.
- **Cannot connect to Tigo API**: a Home Assistant persistent notification is shown while connectivity is down; it clears automatically once polling recovers.
- **Low RSSI alert**: a Home Assistant persistent notification appears when low RSSI persists for the configured debounce window (`rssi_alert_consecutive_polls`) and auto-clears when no modules remain below `rssi_alert_threshold`.
- **Telemetry lag alert**: a Home Assistant persistent notification appears when heartbeat-vs-telemetry lag is critical (`>=45m`) for 2 consecutive summary polls and clears when critical lag resolves.
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
