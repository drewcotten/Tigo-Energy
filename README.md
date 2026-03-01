# Tigo Energy

[![GitHub Release](https://img.shields.io/github/v/release/drewcotten/Tigo-Energy)](https://github.com/drewcotten/Tigo-Energy/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License](https://img.shields.io/github/license/drewcotten/Tigo-Energy)](LICENSE)

Home Assistant custom integration for **Tigo Energy Premium cloud API** telemetry.

This integration supports native UI onboarding (Config Flow), in-flow authentication, and lag-aware telemetry handling for Tigo cloud data.

## Features

- Native Home Assistant onboarding from **Settings > Devices & Services**
- In-flow login with your Tigo account (token obtained internally)
- System summary sensors (power and energy)
- Source health sensors (check-in, control state, firmware, gateway count)
- Optional module-level telemetry (`Pin`, `Vin`, `Iin`, `RSSI`) with configurable polling
- Lag-aware backfill strategy to handle delayed minute data from cloud processing

## Requirements

- Home Assistant `2026.3.0` or newer
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
3. Choose scope:
   - `single_system` (default)
   - `all_systems`
4. If `single_system`, select the system to track.
5. Choose whether to enable module-level telemetry (`Pin`, `Vin`, `Iin`, `RSSI`). Default is `off`.

Reauthentication is supported via Home Assistant UI when credentials/tokens become invalid.

## Options

All options are configurable in **Settings > Devices & Services > Tigo Energy > Configure**:

- `summary_poll_seconds` (default `60`)
- `module_poll_seconds` (default `300`)
- `enable_module_telemetry` (default `false`, also selectable during onboarding)
- `stale_threshold_seconds` (default `3600`)
- `backfill_window_minutes` (default `120`)
- `recent_cutoff_minutes` (default `20`)

## Entities

### System summary

- Current power (`last_power_dc`)
- Daily energy (`daily_energy_dc`)
- YTD energy (`ytd_energy_dc`)
- Lifetime energy (`lifetime_energy_dc`)
- Latest stable data timestamp

### Source health and diagnostics

- Last check-in
- Control state
- Firmware/software version
- Gateway count
- Source serial

### Module telemetry (opt-in)

When `enable_module_telemetry` is true, per-module sensors are created for:

- `Pin` (W)
- `Vin` (V)
- `Iin` (A)
- `RSSI` (dBm)

## Data Freshness and Cloud Lag

Tigo minute data can lag real time because field data and cloud-side processing are not instantaneous.

This integration uses a lag-aware strategy:

- Poll summary/source data at configured cadence
- For module data, query a rolling trailing window
- Exclude very recent minutes (`recent_cutoff_minutes`) to avoid unstable edge data
- Dedupe repeated/late-arriving points
- Mark entities unavailable when data age exceeds `stale_threshold_seconds`

## Troubleshooting

- **Invalid auth**: verify credentials in Tigo portal and run reauthenticate in integration UI.
- **No systems found**: confirm account has system access and Premium/API entitlement.
- **Data appears delayed**: expected with cloud lag; tune `backfill_window_minutes` and `recent_cutoff_minutes`.
- **Too many entities**: disable module telemetry or increase module poll interval.

## Development

```bash
pip install -r requirements_dev.txt
ruff check .
pytest -q
```

## License

[MIT](LICENSE)
