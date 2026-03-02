# Tigo API Integration Notes

This is a practical "stuff you should be aware of" guide for integrating with the Tigo Cloud API used in this repo.

Related docs in this repo:

- `docs/tigo-readonly-alerts-live-probe-2026-03-01.md` (live endpoint probe notes)
- `docs/persistent-notifications-reference.md` (notification behavior and option gates)
- `docs/entity-name-reference.md` (HA naming patterns and examples)

## Audience and Scope

Use this guide when you are building collectors, alerts, automation, or BI ingestion around these endpoints:

- `/users/login`
- `/systems`
- `/systems/{id}`
- `/objects/system`
- `/sources/system`
- `/data/aggregate`
- `/data/combined`
- `/alerts/system`
- `/alerts/types`

## TL;DR (The Important Stuff)

1. Login behavior is not uniform: `POST /users/login` may fail (`404`) while `GET /users/login` works.
2. Token shape can vary (`auth` can be top-level or nested under `user`/`data`).
3. Data endpoints may return CSV (`text/csv`) instead of JSON.
4. `level=min` may be rejected on some endpoints; normalize to `level=minute`.
5. `last_checkin` is source heartbeat freshness, not necessarily module telemetry freshness.
6. CSV telemetry timestamps have no offset; treat them as site-local bucket times before converting.
7. History tabs should be sorted newest->oldest and cleaned for future empty rows (already implemented here).
8. API freshness lag is variable; build lag-aware alerts rather than assuming real-time parity.
9. Short-window history pulls can intermittently return empty history while wider windows return data; treat cause as unresolved and code defensively.

Status in this integration as of the read-only alert/system expansion pass:

- implemented: login fallback (`POST -> GET`), flexible token extraction, proactive token refresh using `expires`, bounded 429 retry with `Retry-After`, site-local CSV timestamp parsing, short-window fallback, and future-row filtering.
- implemented: stale/freshness is surfaced as diagnostics attributes (`system_data_*`, `module_data_*`) while expected cloud lag keeps entities available when coordinator updates are healthy.
- implemented: read-only alert ingestion (`/alerts/system`) with system-level alert entities and shutdown/PV-Off binary sensors.
- implemented: module label canonicalization from `/objects/system` labels (`A1`, `B4`, etc.), with `/system/layout` panel-label fallback and registry migration from raw numeric module IDs when available.
- implemented: sunset-aware alert policy for data-quality notifications (lag/RSSI) using `sun.sun` + recent positive production fallback, with raw vs effective lag status (`telemetry_lag_status_raw` and `telemetry_lag_status`).
- implemented: read-only alert-feed persistent notifications for PV-Off, string shutdown, and active alert summary (auto-clearing on recovery).

## Key Behavioral Quirks

## 1) Authentication Quirk: GET Login Fallback

Observed on this account:

- `POST /users/login` -> `404`
- `GET /users/login` -> `200` with usable token

Practical implication:

- Always implement fallback `POST` -> `GET` for login.
- The Home Assistant integration in this repo now does this by default.

## 2) Token Shape Variability

Observed/handled payload shapes:

- `{ "auth": "...", "expires": "..." }`
- `{ "user": { "auth": "...", "expires": "..." } }`
- `{ "data": { "auth": "...", "expires": "..." } }`

Practical implication:

- Do not hard-code one JSON path for token extraction.
- The Home Assistant integration in this repo now accepts top-level, `user.*`, and `data.*` token containers.

## 3) Content-Type Variability (JSON vs CSV)

Observed:

- metadata/status endpoints return JSON
- telemetry endpoints often return CSV

Practical implication:

- parser must switch by `Content-Type`
- for CSV, map first row to header and each row to dict

## 4) Parameter Strictness

Observed:

- `/data/combined` rejects non-canonical levels like `min`
- accepts canonical values such as `minute`

Practical implication:

- normalize level aliases before sending requests.

## Freshness and Lag: What the Timestamps Actually Mean

Different timestamps represent different pipeline stages.

- `sources[].last_checkin`: source heartbeat recency
- `sources[].sets[]` timestamps: dataset-specific freshness (can lag heavily depending on set)
- `aggregate/combined Datetime`: bucket times for returned telemetry

Do not assume these fields move together.

## Short-Window No-History Anomaly (Confirmed, Root Cause Unresolved)

Confirmed observations from this environment (March 1, 2026, America/Denver):

- a short-window full-detail pull at ~`12:31 PM MST` produced history tabs with header only
- a wider-window pull (`--minutes-back 1440`) two minutes later produced populated history (292 rows, newest bucket at `12:07:00 PM MST`)
- another short-window pull at ~`12:34 PM MST` again produced header-only history

What we can assert:

- this is reproducible behavior in this environment
- it is not safe to assume short lookbacks always return usable recent history

What we cannot assert yet:

- exact backend cause (window timezone interpretation, bucket alignment, latency behavior, or other API internals)

Practical mitigation:

- if short window returns empty history, retry with a wider window and post-filter locally
- keep this behavior documented as a known API quirk, not a guaranteed platform rule
- the Home Assistant integration in this repo now applies this fallback strategy.

## Observed Lag Differentials (This Environment)

Observation date: March 1, 2026 (America/Denver).

Fresh API sample (captured near `12:24 PM MST`):

- source `last_checkin`: `12:14:32 PM MST`
- latest non-empty `Pin` aggregate bucket: `12:07:00 PM MST`
- latest non-empty combined `Pin` bucket: `12:07:00 PM MST`

Computed deltas:

- `now - last_checkin`: ~`9.7 min`
- `last_checkin - latest aggregate Pin`: ~`7.5 min`
- `last_checkin - latest combined Pin`: ~`7.5 min`

Dataset set lag in the same sample (illustrates set-specific staleness):

- `last_checkin - sets[].last_raw`: ~`1103.5 min` (~18.4h)
- `last_checkin - sets[].last_min`: ~`20479.5 min` (~14.2d)

Recent full-detail export observations on the same date also showed higher telemetry lag windows at times (~`36.5` to `38.5` minutes), so lag is not fixed.

Operational takeaway:

- design for a moving lag window, not a single static expected lag.

## Timestamp Handling Rules (Do Not Skip)

Use these parse rules consistently:

1. ISO with offset (`YYYY-MM-DDTHH:MM:SS±HH:MM`): parse as aware instant.
2. Date-only (`YYYY-MM-DD`): treat as date (or local midnight if needed).
3. CSV bucket time (`YYYY/MM/DD HH:MM:SS`): treat as site-local bucket timestamp.

For this repo/site, converted display timezone is:

- `America/Denver` (DST-aware)
- display format in reports: `YYYY-MM-DD hh:mm:ss AM/PM TZ` (non-military)

Known pitfall already fixed in this repo:

- interpreting CSV bucket timestamps as UTC creates a `-7h`/`-6h` Denver shift.
- Home Assistant integration behavior: naive CSV timestamps are parsed using `system timezone -> Home Assistant timezone -> UTC`.

## History Data Quality Rules (Applied by Default Here)

For history sheets (`Pin/Vin/Iin/RSSI Timeseries`, `Combined Pin`), this repo now:

- sorts rows newest -> oldest by Denver timestamp
- drops rows with all-empty metric values
- drops rows more than 5 minutes in the future

Why:

- some raw responses can include timestamp rows with no values
- some windows can include future bucket timestamps

## API Call Budgeting Reality

Typical full-detail run (`full-detail-xlsx`) uses:

- 8 data calls
- plus login call when needed (usually +1)

So: plan for ~9 HTTP calls per run under normal conditions.

Given this repo default limiter (`20 req/min`, burst allowed):

- a single full-detail run is safe
- frequent overlapping runs can still trigger 429 depending on other account consumers

## 429/Retry Behavior You Should Implement

- On `429`, honor `Retry-After` when present.
- If missing, backoff with a conservative default (this repo uses 15s).
- Keep retry count bounded.

Also handle `401` by refreshing/re-login once before hard-failing.

## Practical Alerting Suggestions

Use separate alerts for source heartbeat and telemetry freshness:

- Source stale warning: `now - last_checkin > 15 min`
- Source stale critical: `> 30 min`
- Telemetry lag warning: `last_checkin - latest_non_empty_metric > 20 min`
- Telemetry lag critical: `> 45 min`

Note:

- these thresholds are pragmatic starting points inferred from observed variability in this environment.
- tune them with your own week/month baseline.

## Debug Checklist for “Data Looks Wrong”

1. Check whether parser used JSON vs CSV branch correctly.
2. Verify `level` normalization (`minute`, not `min` for strict endpoints).
3. Confirm `object_ids` includes module objects (`object_type_id == 2`).
4. Check if rows are timestamp-only with empty values.
5. Verify timestamp timezone interpretation (site-local for CSV buckets).
6. Compare `last_checkin` vs latest non-empty telemetry to classify lag vs outage.
7. Inspect RSSI outliers before concluding hardware failures.
8. If short-window history is empty, rerun with a wider lookback before assuming no production history exists.

## Recommended Contract for Downstream Workers

When handing to another worker/service, specify these invariants:

- parse login token from multiple possible payload locations
- support CSV and JSON responses
- keep both raw and normalized timestamp columns
- use Denver DST-aware conversion for display
- apply history cleanup filters (empty/future rows)
- compute lag deltas explicitly and store them as numeric minutes
