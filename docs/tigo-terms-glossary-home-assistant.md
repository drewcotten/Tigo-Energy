# Tigo Terms Glossary (Home Assistant Mapping)

This is a Home Assistant-focused copy of the Tigo glossary that maps API terms to entities and attributes created by this integration.

Scope:

- terms and fields this integration currently consumes
- direct mapping to Home Assistant sensors/attributes where applicable
- explicit callout when a term is internal-only (used by polling/parsing logic but not exposed as a sensor)

Notes:

- Entity IDs are dynamically generated from config entry/system/source/panel context.
- Sensor names below reference translation keys defined by the integration.
- Array telemetry sensors exist when `enable_array_telemetry` is enabled (default `true`).
- Panel telemetry sensors exist only when `enable_panel_telemetry` is enabled (default `false`).

## Telemetry and Metrics

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `Pin` | `module_pin`, `array_power` | Yes (panel on / array on) | Panel input power (W) and derived per-array total power. |
| `Vin` | `module_vin`, `array_voltage`, `array_voltage_average`, `array_voltage_min`, `array_voltage_max` | Yes (panel on / array on) | Panel voltage and derived per-array voltage diagnostics. |
| `Iin` | `module_iin`, `array_current_average`, `array_current_min`, `array_current_max` | Yes (panel on / array on) | Panel current and derived per-array current diagnostics. |
| `RSSI` | `module_rssi`, `array_rssi_*`, `low_rssi_module_count`, `watch_rssi_module_count`, `worst_module_rssi` | Yes (panel on / array on) | Panel RSSI plus array/system RSSI diagnostics. |
| `Combined Pin` (`/data/combined?param=Pin`) | `telemetry_lag_minutes` (derived), `heartbeat_age_minutes` (derived) | Yes (derived diagnostics) | Combined Pin buckets drive telemetry freshness lag calculations. |
| `Datetime` (telemetry rows) | Internal parsing input | No (raw) | Parsed as site-local bucket time (`system timezone -> HA timezone -> UTC`). |
| `param` | Internal request parameter | No | Metric selector for aggregate/combined calls. |
| `level` | Internal request parameter | No | Normalized to `minute` for integration telemetry queries. |
| `start` / `end` | Internal request window | No | Site-local wall-clock query bounds derived from lag-aware polling windows. |

## System Metadata

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `system_id` | Device identifier (`system_<id>`), entity unique IDs | Indirect | Used for stable identity and entity/device construction. |
| `name` (system) | Device name | Yes (device metadata) | Displayed as Home Assistant device name. |
| `power_rating` | Runtime metadata only | No sensor | Stored in runtime snapshot; not currently a dedicated entity. |
| `turn_on_date` | Runtime metadata only | No sensor | Stored in runtime snapshot; not currently a dedicated entity. |
| `commissioned` | API metadata only | No sensor | Not currently surfaced as an entity. |
| `created` (system) | API metadata only | No sensor | Not currently surfaced as an entity. |
| `timezone` (system) | Timezone resolution input | Indirect | Used to parse naive CSV bucket timestamps correctly. |
| `street/city/state/zip/country` | Runtime metadata only | No sensor | Not currently surfaced as dedicated entities. |

## Source / Gateway Status

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `source_id` | Source device identifier and unique IDs | Indirect | Used for source entity/device identity. |
| `name` (source) | Source device name | Yes (device metadata) | Displayed as source device name. |
| `serial` | `source_serial` | Yes | Source serial diagnostic sensor. |
| `sw_version` | `source_sw_version` | Yes | Firmware/software version diagnostic sensor. |
| `gateway_count` | `source_gateway_count` | Yes | Topology diagnostic sensor. |
| `control_state` | `source_control_state` | Yes | Source state sensor (for example PV on/off control mode). |
| `last_checkin` | `source_last_checkin`, `heartbeat_age_minutes` (derived) | Yes | Direct source heartbeat sensor plus derived age metric. |
| `created_on` | API metadata only | No sensor | Not currently surfaced as an entity. |
| `sets[].set_name` | Runtime parsing context | No sensor | Used as source freshness context only. |
| `sets[].last_day` | Source freshness inference | Indirect | Considered in source freshness extraction; not its own sensor. |
| `sets[].last_min` | Source freshness inference | Indirect | Considered in source freshness extraction; not its own sensor. |
| `sets[].last_raw` | Source freshness inference | Indirect | Considered in source freshness extraction; not its own sensor. |

## Object Tree / Topology

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `id` / `object_id` / `panel_id` | Panel identity fallback mapping | Indirect | Used to map raw telemetry keys to semantic panel labels and array membership. |
| `label` | Panel and array naming | Yes (indirect) | Used for user-facing panel labels (`A1`, `B12`) and array names. |
| `string_id` / `short_label` | Array identity and naming | Yes (indirect) | Used to build array IDs/names and panel-to-array mapping. |
| `mppt_id` / inverter linkage fields | Array context attributes | Yes (indirect) | Used for array metadata attributes (MPPT/inverter context). |
| `object_type_id` / `parent_id` / `children` / `datasource` | Not currently mapped | No | Not required for current sensor/entity model. |
| `object_ids` (query param) | Not currently used | No | Current polling reads system-wide aggregate/combined windows. |
| `header=key` | Internal API option | No | Aggregate polling requests key headers so semantic panel labels can be parsed when provided. |

## Auth and API Metadata

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `auth` | Internal bearer token state | No | Stored in memory only; never exposed as an entity. |
| `expires` | Internal token refresh logic | No | Used for proactive token renewal when available. |
| `refresh_token` | Not currently mapped | No | Not currently used by integration auth flow. |
| `_links` | Internal pagination metadata | No | Used only if needed for API list handling. |
| `_meta.currentPage/pageCount/perPage/totalCount` | Internal pagination metadata | No | Not surfaced in Home Assistant entities. |

## Integration-Derived Diagnostics (Home Assistant)

These are not raw Tigo field names, but the integration computes and exposes them:

| Derived field | Home Assistant mapping | Notes |
|---|---|---|
| Latest stable timestamp | `latest_stable_data_timestamp` | System-level freshness sensor. |
| Stale/freshness flags | `is_stale`, `data_lag_seconds`, `system_data_*`, `module_data_*` attributes | Added to coordinator-backed entities for global + per-system/per-panel freshness context. |
| Telemetry lag | `telemetry_lag_minutes` + attributes | Attributes include `telemetry_lag_status`, thresholds, and timestamp references. |
| Heartbeat age | `heartbeat_age_minutes` + attributes | Derived from latest source heartbeat recency. |
| RSSI status label | `rssi_status` attribute on `module_rssi` | Values: `good`, `watch`, `alert`. |
