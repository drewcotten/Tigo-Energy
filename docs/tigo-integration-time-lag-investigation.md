# Tigo Integration Time-Lag Investigation (v1.0)

Date: 2026-03-01  
Scope: Code-audit first (no runtime experiments), Home Assistant docs verification, decision-ready recommendations.

## Executive Conclusion

Will this integration work? **Yes, with an important constraint**:

- It works as a **latest-state polling integration** with lag diagnostics and stale handling.
- It does **not** currently provide true retroactive historical reconstruction of delayed minute buckets in Home Assistant charts.

Primary finding (time-lag/backfill):

- The integration correctly handles delayed cloud data for selecting a stable latest value (lag-aware windows, fallback, dedupe).
- But it publishes only the latest point per metric/module to entity state, so Home Assistant history reflects **when HA received/accepted updates**, not the original minute-bucket timeline from Tigo.

Inference from HA docs + current code: because HA entities hold one current state at a time and state changes/events are driven by writes to the state machine, this architecture cannot backfill old minute points into historical charts retroactively.

## 1) Source-of-Truth Map (Lag/Freshness Paths)

## API and parsing

- Auth/login fallback and token extraction variants:
  - `custom_components/tigo_energy/api.py:107`
  - `custom_components/tigo_energy/api.py:109`
  - `custom_components/tigo_energy/api.py:421`
- 401 retry-after-relogin behavior:
  - `custom_components/tigo_energy/api.py:243`
  - `custom_components/tigo_energy/api.py:246`
  - `custom_components/tigo_energy/api.py:249`
- 429 bounded retry handling with `Retry-After` parsing:
  - `custom_components/tigo_energy/api.py:257`
  - `custom_components/tigo_energy/api.py:275`
  - `custom_components/tigo_energy/api.py:457`
- Timestamp parser and naive timezone injection:
  - `custom_components/tigo_energy/api.py:319`
  - `custom_components/tigo_energy/api.py:322`
- CSV parsing with future-row dropping and invalid timestamp counters:
  - `custom_components/tigo_energy/api.py:369`
  - `custom_components/tigo_energy/api.py:395`
  - `custom_components/tigo_energy/api.py:414`

## Summary coordinator (system/source + lag diagnostics)

- Lag-aware window uses `recent_cutoff` and `backfill`:
  - `custom_components/tigo_energy/coordinator.py:134`
  - `custom_components/tigo_energy/coordinator.py:135`
- Always-on combined Pin freshness fetch:
  - `custom_components/tigo_energy/coordinator.py:165`
  - `custom_components/tigo_energy/coordinator.py:290`
- Heartbeat age and telemetry lag split:
  - `custom_components/tigo_energy/coordinator.py:208`
  - `custom_components/tigo_energy/coordinator.py:214`
  - `custom_components/tigo_energy/coordinator.py:221`
- Critical lag notification debounce:
  - `custom_components/tigo_energy/coordinator.py:343`
  - `custom_components/tigo_energy/coordinator.py:345`
- Summary stale calculation (global latest):
  - `custom_components/tigo_energy/coordinator.py:267`
  - `custom_components/tigo_energy/coordinator.py:268`

## Module coordinator (module telemetry + fallback + dedupe)

- Lag-aware query window:
  - `custom_components/tigo_energy/coordinator.py:447`
  - `custom_components/tigo_energy/coordinator.py:448`
- Empty-window fallback and filter-back-to-original-window:
  - `custom_components/tigo_energy/coordinator.py:565`
  - `custom_components/tigo_energy/coordinator.py:591`
  - `custom_components/tigo_energy/coordinator.py:606`
  - `custom_components/tigo_energy/coordinator.py:765`
- Latest-point selection and dedupe suppression of older/equal timestamps:
  - `custom_components/tigo_energy/coordinator.py:496`
  - `custom_components/tigo_energy/coordinator.py:499`
- Module stale calculation (global latest across all module points):
  - `custom_components/tigo_energy/coordinator.py:531`
  - `custom_components/tigo_energy/coordinator.py:532`

## Entity availability/state exposure

- Base availability keyed to summary global staleness:
  - `custom_components/tigo_energy/sensor.py:374`
  - `custom_components/tigo_energy/sensor.py:375`
- Module availability keyed to module global staleness plus point existence:
  - `custom_components/tigo_energy/sensor.py:561`
  - `custom_components/tigo_energy/sensor.py:566`
  - `custom_components/tigo_energy/sensor.py:569`
- Lag diagnostic sensor values/attributes:
  - `custom_components/tigo_energy/sensor.py:436`
  - `custom_components/tigo_energy/sensor.py:455`

## Setup/retry/reauth semantics

- Startup auth failure path currently raises `ConfigEntryNotReady`:
  - `custom_components/tigo_energy/__init__.py:70`
  - `custom_components/tigo_energy/__init__.py:73`
- Runtime poll auth failure raises `ConfigEntryAuthFailed` (via coordinators):
  - `custom_components/tigo_energy/coordinator.py:108`
  - `custom_components/tigo_energy/coordinator.py:149`
  - `custom_components/tigo_energy/coordinator.py:475`

## 2) Data Flow (API -> Coordinator -> Entity -> HA History)

1. Integration fetches Tigo summary/source/aggregate CSV.
2. CSV timestamps are parsed, normalized to UTC, future rows dropped.
3. Coordinators compute latest stable values and freshness diagnostics.
4. Entities expose one current state (`native_value`) plus attributes.
5. HA writes current entity state to state machine.
6. Recorder/history reflect HA state writes/changes, not a retroactive insert of historical minute buckets from integration memory.

Inference: step 6 means delayed bucket arrival can update current state later, but does not reconstruct the missing older minute-by-minute line as if it had arrived on time.

## 3) Validation Against Official Home Assistant Semantics

Official references:

- State object semantics (single current state, `last_changed`, `last_updated`, `last_reported`):
  - [State and state object](https://www.home-assistant.io/docs/configuration/state_object/)
- State change event semantics:
  - [Events](https://www.home-assistant.io/docs/configuration/events/)
- Polling/coordinator write model and `async_write_ha_state`:
  - [Fetching data](https://developers.home-assistant.io/docs/integration_fetching_data/)
- Availability expectations:
  - [Mark entity unavailable if appropriate](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unavailable/)
- Setup failure and reauth trigger semantics:
  - [Handling setup failures](https://developers.home-assistant.io/docs/integration_setup_failures/)
- State write behavior update (`last_reported`):
  - [New state timestamp State.last_reported](https://developers.home-assistant.io/blog/2024/03/20/state_reported_timestamp/)
- External statistics import APIs (for alternate architecture):
  - [Changes to the recorder statistics API](https://developers.home-assistant.io/blog/2025/10/16/recorder-statistics-api-changes/)

### README claim classification

| Claim | Classification | Why |
|---|---|---|
| Lag-aware trailing window, recent cutoff, rolling backfill | Accurate | Implemented in summary/module coordinators (`coordinator.py:134`, `coordinator.py:447`, `coordinator.py:565`). |
| Empty-window widened retry | Accurate | Implemented in both summary combined fetch and module fetch (`coordinator.py:315`, `coordinator.py:591`). |
| Marks entities unavailable when data age exceeds stale threshold | Incomplete | True at coordinator-level freshness, but freshness is global not per-system/per-module (`sensor.py:375`, `sensor.py:566` + coordinator global lag calculations). |
| “Short chart gaps can appear and then fill in later as delayed buckets are backfilled” (`README.md:49`) | Incorrect for current architecture | Current code keeps latest point only and suppresses older arrivals (`coordinator.py:499`). HA state history is write/change-driven, not historical minute-bucket import for these sensors. |

## 4) Scenario-Based Static Simulation

## Scenario 1: Short-window empty, wide-window non-empty two polls later

- Coordinator behavior:
  - Poll N: primary empty -> fallback attempted -> may still yield no points (`coordinator.py:565`).
  - Poll N+2: points appear -> latest point stored (`coordinator.py:496`).
- Entity behavior:
  - State remains old/unknown until a newer accepted point arrives.
- HA history outcome:
  - History gets update at arrival/write time, not backdated minute-bucket reconstruction.
- Risk:
  - User may perceive “missing historical minutes” even when data eventually appears upstream.

## Scenario 2: Midday 5-30 minute API gap, then delayed return

- Coordinator behavior:
  - Delayed points are parsed and considered, but only max timestamp per module/metric is applied.
- Entity behavior:
  - If delayed point is newer than cached point, state updates now.
  - If delayed point is older/equal than cached point, it is ignored.
- HA history outcome:
  - No retroactive insertion for gap minutes in chart timeline.

## Scenario 3: Late-arriving point older than already-published latest point

- Coordinator behavior:
  - Explicitly ignored by dedupe guard (`coordinator.py:499`).
- Entity behavior:
  - No state change.
- HA history outcome:
  - That older point is never represented in entity state history.
- Risk:
  - Real delayed telemetry can be silently dropped from user-visible history.

## Scenario 4: Continuous lag beyond warning/critical thresholds

- Coordinator behavior:
  - `telemetry_lag_status` computed from heartbeat vs telemetry (`coordinator.py:221`).
  - Critical notification after consecutive-poll debounce (`coordinator.py:345`).
- Entity behavior:
  - Lag sensors report increasing lag.
  - Availability may remain true until stale threshold is crossed.
- HA history outcome:
  - Lag sensor history is accurate for lag trend; production metrics still latest-state only.

## Scenario 5: Heartbeat fresh but telemetry lagging

- Coordinator behavior:
  - Split metrics support this diagnosis (`heartbeat_age_seconds` and `telemetry_lag_seconds`).
- Entity behavior:
  - `heartbeat_age` low, `telemetry_lag` high, status warning/critical.
- HA history outcome:
  - Diagnostic behavior is consistent with intended semantics.

## 5) Reliability and Risk Matrix

| Risk | Trigger | Current handling | Residual gap | Severity | Confidence |
|---|---|---|---|---|---|
| Historical backfill representation mismatch | Delayed minute buckets arrive late | Latest-state model + dedupe | No retroactive chart reconstruction | High | High |
| False confidence from “latest stable” wording | User interprets as complete minute history | Freshness/lag sensors provided | Still easy to over-assume chart completeness | High | High |
| Stale threshold too permissive/strict outcomes | Variable cloud lag patterns | Configurable `stale_threshold_seconds` | One threshold cannot fit all installations; no adaptive mode | Medium | Medium |
| Dedupe suppressing older late points | Out-of-order bucket delivery | Ignore `<= current.timestamp` | Older delayed points are never represented | High | High |
| Empty-window fallback false negatives | API returns data outside filtered original window | One widened retry + local filter | Can still miss useful delayed data | Medium | Medium |
| 429/auth/retry interaction under lag | API pressure + lag periods | Client retries 429 and 401 paths | Coordinator does not pass `retry_after`; may keep pressure at poll cadence after retries exhaust | Medium | Medium |
| Global freshness hides per-system staleness | One system fresh, another stale (all-systems mode) | Summary availability uses global freshness | Stale systems can appear available | High | High |
| Global module freshness hides per-module staleness | Some modules update, others stop | Module availability uses global module freshness | Stale modules can appear available if any module stays fresh | High | High |

## 6) Option Analysis (Decision Package)

## Option A: Keep latest-state model, tighten docs/UI semantics only

- Engineering complexity: Low
- HA compatibility: High
- User expectation fit: Medium-Low (for users expecting real timeline reconstruction)
- Risk reduction: Medium (communication clarity improves, core mismatch remains)
- Migration impact: None

## Option B: Add history-correctness architecture for delayed buckets

- Approach:
  - Keep existing latest-state sensors for live dashboards.
  - Add external statistics import path for reconstructed historical aggregates where feasible (using HA recorder statistics APIs).
- Engineering complexity: High
- HA compatibility: Medium-High (uses supported stats APIs, but different data model than entity state timeline)
- User expectation fit: High for historical analytics, Medium for exact minute-level parity
- Risk reduction: High
- Migration impact: Medium (new entities/statistics IDs and docs)

## Option C: Hybrid (recommended)

- Approach:
  - Keep latest-state sensors.
  - Fix per-system/per-module freshness semantics.
  - Correct README/UI wording and surface explicit “history mode limitations”.
  - Optionally add statistics import in phase 2.
- Engineering complexity: Medium now, High with phase 2
- HA compatibility: High
- User expectation fit: High once semantics are explicit
- Risk reduction: High for immediate confusion + correctness gaps
- Migration impact: Low-Medium

Recommended path: **Option C**.

## 7) Prioritized Remediation Actions (Next Cycle)

1. Replace README wording that implies retroactive chart backfill (`README.md:49`) with explicit latest-state semantics.
2. Implement per-system stale availability in summary entities (avoid global-only staleness).
3. Implement per-module stale availability using each module point timestamp (not global module freshness only).
4. Add explicit entity attributes that distinguish:
   - data timestamp (`module_latest_timestamp`) vs
   - HA write/report time (`last_reported` concept in docs, user education)
5. Evaluate optional history path:
   - statistics import for reconstructed historical aggregates (phase 2).
6. Consider coordinator `UpdateFailed(retry_after=...)` strategy for persistent 429 periods (aligned with modern HA coordinator guidance).

## 8) Evidence Appendix

## Repo evidence references

- API retry/auth/timestamp logic:
  - `custom_components/tigo_energy/api.py:107`
  - `custom_components/tigo_energy/api.py:243`
  - `custom_components/tigo_energy/api.py:257`
  - `custom_components/tigo_energy/api.py:319`
  - `custom_components/tigo_energy/api.py:369`
- Summary/module lag and fallback logic:
  - `custom_components/tigo_energy/coordinator.py:134`
  - `custom_components/tigo_energy/coordinator.py:165`
  - `custom_components/tigo_energy/coordinator.py:221`
  - `custom_components/tigo_energy/coordinator.py:267`
  - `custom_components/tigo_energy/coordinator.py:496`
  - `custom_components/tigo_energy/coordinator.py:499`
  - `custom_components/tigo_energy/coordinator.py:531`
  - `custom_components/tigo_energy/coordinator.py:565`
  - `custom_components/tigo_energy/coordinator.py:765`
- Entity availability behavior:
  - `custom_components/tigo_energy/sensor.py:375`
  - `custom_components/tigo_energy/sensor.py:566`
- Setup auth behavior:
  - `custom_components/tigo_energy/__init__.py:70`
  - `custom_components/tigo_energy/__init__.py:73`
- README claim under review:
  - `README.md:49`

## Home Assistant docs used

- [State and state object](https://www.home-assistant.io/docs/configuration/state_object/)
- [Events](https://www.home-assistant.io/docs/configuration/events/)
- [Fetching data](https://developers.home-assistant.io/docs/integration_fetching_data/)
- [Handling setup failures](https://developers.home-assistant.io/docs/integration_setup_failures/)
- [Mark entity unavailable if appropriate](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unavailable/)
- [New state timestamp State.last_reported](https://developers.home-assistant.io/blog/2024/03/20/state_reported_timestamp/)
- [Changes to the recorder statistics API](https://developers.home-assistant.io/blog/2025/10/16/recorder-statistics-api-changes/)

---

No runtime behavior was modified in this pass. This deliverable is investigation/report only.
