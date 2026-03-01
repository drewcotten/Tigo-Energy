# Tigo Terms Glossary (Home Assistant Mapping)

This is a Home Assistant-focused copy of the Tigo glossary that maps API terms to entities and attributes created by this integration.

Scope:

- terms and fields this integration currently consumes
- direct mapping to Home Assistant sensors/attributes where applicable
- explicit callout when a term is internal-only (used by polling/parsing logic but not exposed as a sensor)

Notes:

- Entity IDs are dynamically generated from config entry/system/source/module context.
- Sensor names below reference translation keys defined by the integration.
- Module sensors exist only when `enable_module_telemetry` is enabled.

## Telemetry and Metrics

| Tigo term | Home Assistant mapping | Exposed | Notes |
|---|---|---|---|
| `Pin` | `module_pin` | Yes (module telemetry on) | Per-module input power sensor (W). |
| `Vin` | `module_vin` | Yes (module telemetry on) | Per-module input voltage sensor (V). |
| `Iin` | `module_iin` | Yes (module telemetry on) | Per-module input current sensor (A). |
| `RSSI` | `module_rssi`, `low_rssi_module_count`, `watch_rssi_module_count`, `worst_module_rssi` | Yes (module telemetry on) | Per-module RSSI plus system-level RSSI aggregate diagnostics. |
| `Combined Pin` (`/data/combined?param=Pin`) | `telemetry_lag_minutes` (derived), `heartbeat_age_minutes` (derived) | Yes (derived diagnostics) | Combined Pin buckets drive telemetry freshness lag calculations. |
| `Datetime` (telemetry rows) | Internal parsing input | No (raw) | Parsed as site-local bucket time (`system timezone -> HA timezone -> UTC`). |
| `param` | Internal request parameter | No | Metric selector for aggregate/combined calls. |
| `level` | Internal request parameter | No | Normalized to `minute` for integration telemetry queries. |
| `start` / `end` | Internal request window | No | UTC ISO query bounds used by lag-aware polling and fallback. |

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
| `id` (object) | Not currently mapped | No | Not used for current entity model. |
| `label` | Not currently mapped | No | Not used for current entity model. |
| `object_type_id` | Not currently mapped | No | Not used for current entity model. |
| `parent_id` | Not currently mapped | No | Not used for current entity model. |
| `children` | Not currently mapped | No | Not used for current entity model. |
| `datasource` | Not currently mapped | No | Not used for current entity model. |
| `object_ids` (query param) | Not currently mapped | No | Not used by current polling implementation. |
| `header=key` | Internal API option | No | Current integration uses aggregate/combined CSV header handling internally. |

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
| Stale flag and lag | `is_stale`, `data_lag_seconds` attributes | Added to coordinator-backed entities. |
| Telemetry lag | `telemetry_lag_minutes` + attributes | Attributes include `telemetry_lag_status`, thresholds, and timestamp references. |
| Heartbeat age | `heartbeat_age_minutes` + attributes | Derived from latest source heartbeat recency. |
| RSSI status label | `rssi_status` attribute on `module_rssi` | Values: `good`, `watch`, `alert`. |
