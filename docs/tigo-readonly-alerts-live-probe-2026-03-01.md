# Tigo Read-Only Alerts Live Probe (2026-03-01)

## Purpose
Quickly validate what the Tigo v3 API currently returns for read-only alert/system monitoring so we can scope implementation in the Home Assistant integration.

## Test method
- Tooling: `/Users/drewcotten/Github/raw-tigo` (`TigoClient` + authenticated endpoint probes)
- Date/time: 2026-03-01 (America/Denver)
- Calls kept low (well below 30/min)
- System tested: `system_id=<SYSTEM_ID>`

Raw artifact:
- `/Users/drewcotten/Github/raw-tigo/data/alert_readonly_probe_<SYSTEM_ID>_20260301T233946Z.json`

## Endpoints tested and results

| Endpoint | Result | Observed response shape | Notes |
|---|---|---|---|
| `GET /alerts/system?system_id=<SYSTEM_ID>` | `200` | `{ "alerts": [...], "_links": {...}, "_meta": {...} }` | Active alerts were `0` at test time. `_meta` present and usable for count/paging. |
| `GET /alerts/types` | `200` | `{ "alert_types": [...] }` | Returned 9 types; includes stable `unique_id` + title text for classification/mapping. |
| `GET /alerts/view?id=<SYSTEM_ID>&language=EN` | `404` | n/a | Not reliable for this account/host; should not be required in MVP. |
| `GET /alert-subs/list?id=<SYSTEM_ID>` | `200` | `{ "api_event_subs": [...] }` | Returned 10 event subscription definitions, including PV-Off shutdown message title text. |
| `GET /sources/system?system_id=<SYSTEM_ID>` | `200` | `{ "sources": [...] }` | `control_state`, `last_checkin`, `sw_version`, `gateway_count` available. |
| `GET /data/summary?system_id=<SYSTEM_ID>` | `200` | `{ "summary": {...} }` | `last_power_dc`, daily/YTD/lifetime energy available. |
| `GET /objects/system?system_id=<SYSTEM_ID>` | `200` | `{ "objects": [...] }` | Object `label` contains user-facing module labels (`A1`, `A2`, `B4`, `C10`, etc.). |

## Key payload examples (sanitized)

### `/alerts/system`
```json
{
  "alerts": [],
  "_meta": {
    "totalCount": 0,
    "pageCount": 0,
    "currentPage": 1,
    "perPage": 50
  }
}
```

### `/alerts/types`
```json
{
  "alert_types": [
    {
      "alert_type_id": 47,
      "unique_id": 1000,
      "title": "Tigo Alert: Tigo EI Inverter Fault"
    }
  ]
}
```

### `/alert-subs/list` (PV-Off evidence)
```json
{
  "api_event_subs": [
    {
      "event_type_id": 42,
      "message_title": "Tigo Alert: PV-Off Activated &mdash; System Shutdown",
      "notification_sub": null
    }
  ]
}
```

### `/sources/system`
```json
{
  "sources": [
    {
      "name": "Primary CCA",
      "last_checkin": "2026-03-01T15:34:33-08:00",
      "control_state": "on",
      "sw_version": "RandevuConfig_04C05B9FA214.img",
      "gateway_count": 1
    }
  ]
}
```

### `/objects/system` module labels
Observed labels include: `A1..A12`, `B1..B12`, `C1..C9`.

## What this means for HA implementation (read-only scope)

1. Primary alert feed should be `GET /alerts/system`.
2. `GET /alerts/types` can enrich classification and improve user-facing mapping.
3. `GET /alerts/view` should be treated as optional/non-critical due to observed `404`.
4. PV-Off/shutdown detection can be built from two sources:
   - authoritative live state: `sources[].control_state`
   - alert semantics/catalog text: `alerts/system` + `alert-subs/list` titles/unique IDs
5. Module naming should map module object IDs to `/objects/system` `label` values to surface names like `A1`, `B4`, etc.

## Proposed entity set (next implementation pass)

### System-level alert sensors
- `sensor.tigo_active_alert_count`
- `sensor.tigo_latest_alert_title`
- `sensor.tigo_latest_alert_code` (from `unique_id` when present)
- `sensor.tigo_latest_alert_time` (`generated` preferred, fallback `added`)

### Binary sensors
- `binary_sensor.tigo_pv_off_active` (from `control_state` + optional alert corroboration)
- `binary_sensor.tigo_string_shutdown_active` (pattern/ID match on current alert feed)

### Attributes (recommended)
- `latest_alert_message`
- `latest_alert_archived`
- `latest_alert_id`
- `latest_alert_type_id` (if resolvable)
- `alert_feed_timestamp`

## Implementation notes / guardrails
- Keep this pass read-only: do **not** call `PUT /alerts/archive` or `PUT /alerts/unarchive`.
- Handle payload-key variants defensively (`alert_types` vs older/plural naming found in docs).
- If alert list is empty, keep entities available with neutral values (`0`, `none`) rather than marking unavailable.
- Poll alerts on summary cadence to avoid excess calls.
- Continue to respect Tigo rate limits and existing retry behavior.

## Open questions before coding
1. Should `archived=true` alerts count toward `active_alert_count`? (recommended: no)
2. Do you want latest alert sensors hidden/disabled by default when there are no alerts?
3. For shutdown detection, should we strictly require known `unique_id` values, or allow title/message regex fallback immediately?
