# Persistent Notifications Reference

This integration can create the following Home Assistant persistent notifications.

## 1) Connection Issue

- Title: `Tigo Energy: Connection issue`
- Trigger: Setup or polling cannot reach the Tigo API.
- Clear condition: Connectivity recovers.
- Sunset guard: No (always active).

## 2) Low RSSI Alert

- Title: `Tigo Energy: Low RSSI alert`
- Trigger: One or more panels remain below `rssi_alert_threshold` for `rssi_alert_consecutive_polls`.
- Clear condition: No panels remain below threshold, or alerting is suppressed by sunset guard context.
- Sunset guard: Yes (data-quality alert).

## 3) Telemetry Lag Alert

- Title: `Tigo Energy: Telemetry lag alert`
- Trigger: Effective telemetry lag is `critical` for debounce polls.
- Clear condition: No systems remain in effective critical lag.
- Sunset guard: Yes (data-quality alert).

## 4) PV-Off Active

- Title: `Tigo Energy: PV-Off active`
- Trigger: Any tracked system reports PV-Off active.
- Clear condition: No tracked systems report PV-Off active.
- Sunset guard: No (safety/operational alert).

## 5) String Shutdown Alert

- Title: `Tigo Energy: String shutdown alert`
- Trigger: Any tracked system reports string-shutdown active.
- Clear condition: No tracked systems report string-shutdown active.
- Sunset guard: No (safety/operational alert).

## 6) Active System Alerts

- Title: `Tigo Energy: Active system alerts`
- Trigger: Active Tigo alert count is greater than zero.
- Clear condition: Active alert count returns to zero.
- Sunset guard: No (alert-feed summary).

## Option Gates

- `enable_persistent_notifications`:
  - If `false`, none of the notifications above are created.
- `enable_alert_feed_notifications`:
  - Controls only alert-feed notifications:
    - PV-Off active
    - String shutdown alert
    - Active system alerts
- `enable_sunset_alert_guard`:
  - Applies only to data-quality notifications:
    - Low RSSI alert
    - Telemetry lag alert
