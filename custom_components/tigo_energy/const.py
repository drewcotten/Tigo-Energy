"""Constants for the Tigo Energy integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "tigo_energy"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BINARY_SENSOR]

MANUFACTURER: Final = "Tigo Energy"

CONF_ENTRY_MODE: Final = "entry_mode"
CONF_SYSTEM_ID: Final = "system_id"
CONF_SYSTEM_IDS: Final = "system_ids"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
SUBENTRY_TYPE_SYSTEM: Final = "system"

ENTRY_MODE_SINGLE_SYSTEM: Final = "single_system"
ENTRY_MODE_ALL_SYSTEMS: Final = "all_systems"

OPT_SUMMARY_POLL_SECONDS: Final = "summary_poll_seconds"
OPT_MODULE_POLL_SECONDS: Final = "module_poll_seconds"
OPT_ENABLE_MODULE_TELEMETRY: Final = "enable_module_telemetry"
OPT_ENABLE_PERSISTENT_NOTIFICATIONS: Final = "enable_persistent_notifications"
OPT_NOTIFY_CONNECTION_ISSUES: Final = "notify_connection_issues"
OPT_NOTIFY_LOW_RSSI: Final = "notify_low_rssi"
OPT_NOTIFY_TELEMETRY_LAG: Final = "notify_telemetry_lag"
OPT_NOTIFY_PV_OFF: Final = "notify_pv_off"
OPT_NOTIFY_STRING_SHUTDOWN: Final = "notify_string_shutdown"
OPT_NOTIFY_ACTIVE_ALERT_SUMMARY: Final = "notify_active_alert_summary"
OPT_ENABLE_SUNSET_ALERT_GUARD: Final = "enable_sunset_alert_guard"
OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: Final = "sun_guard_min_elevation_degrees"
OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: Final = "sun_guard_positive_power_grace_minutes"
OPT_ENABLE_ALERT_FEED_NOTIFICATIONS: Final = "enable_alert_feed_notifications"
OPT_STALE_THRESHOLD_SECONDS: Final = "stale_threshold_seconds"
OPT_BACKFILL_WINDOW_MINUTES: Final = "backfill_window_minutes"
OPT_RECENT_CUTOFF_MINUTES: Final = "recent_cutoff_minutes"
OPT_RSSI_WATCH_THRESHOLD: Final = "rssi_watch_threshold"
OPT_RSSI_ALERT_THRESHOLD: Final = "rssi_alert_threshold"
OPT_RSSI_ALERT_CONSECUTIVE_POLLS: Final = "rssi_alert_consecutive_polls"

DEFAULT_SUMMARY_POLL_SECONDS: Final = 60
DEFAULT_MODULE_POLL_SECONDS: Final = 300
DEFAULT_ENABLE_MODULE_TELEMETRY: Final = False
DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS: Final = True
DEFAULT_NOTIFY_CONNECTION_ISSUES: Final = True
DEFAULT_NOTIFY_LOW_RSSI: Final = False
DEFAULT_NOTIFY_TELEMETRY_LAG: Final = False
DEFAULT_NOTIFY_PV_OFF: Final = True
DEFAULT_NOTIFY_STRING_SHUTDOWN: Final = True
DEFAULT_NOTIFY_ACTIVE_ALERT_SUMMARY: Final = False
DEFAULT_ENABLE_SUNSET_ALERT_GUARD: Final = True
DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES: Final = 3.0
DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: Final = 90
DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS: Final = True
DEFAULT_STALE_THRESHOLD_SECONDS: Final = 1800
DEFAULT_BACKFILL_WINDOW_MINUTES: Final = 120
DEFAULT_RECENT_CUTOFF_MINUTES: Final = 0
DEFAULT_RSSI_WATCH_THRESHOLD: Final = 120
DEFAULT_RSSI_ALERT_THRESHOLD: Final = 80
DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 3
DEFAULT_429_BACKOFF_SECONDS: Final = 15
DEFAULT_TOKEN_REFRESH_LEAD_SECONDS: Final = 300

MIN_SUMMARY_POLL_SECONDS: Final = 15
MIN_MODULE_POLL_SECONDS: Final = 30
MIN_STALE_THRESHOLD_SECONDS: Final = 300
MIN_BACKFILL_WINDOW_MINUTES: Final = 30
MIN_RECENT_CUTOFF_MINUTES: Final = 0
MIN_SUN_GUARD_MIN_ELEVATION_DEGREES: Final = -6.0
MIN_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: Final = 15
MIN_RSSI_THRESHOLD: Final = 0
MIN_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 1

MAX_POLL_SECONDS: Final = 3600
MAX_STALE_THRESHOLD_SECONDS: Final = 21600
MAX_BACKFILL_WINDOW_MINUTES: Final = 360
MAX_RECENT_CUTOFF_MINUTES: Final = 60
MAX_SUN_GUARD_MIN_ELEVATION_DEGREES: Final = 15.0
MAX_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: Final = 360
MAX_RSSI_THRESHOLD: Final = 255
MAX_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 20
MAX_429_RETRIES: Final = 3
MAX_429_BACKOFF_SECONDS: Final = 30

MAX_FUTURE_BUCKET_MINUTES: Final = 5
EMPTY_WINDOW_FALLBACK_MINUTES_MIN: Final = 240
EMPTY_WINDOW_FALLBACK_MINUTES_MAX: Final = 1440

LAG_WARNING_MINUTES: Final = 20
LAG_CRITICAL_MINUTES: Final = 45
LAG_CRITICAL_CONSECUTIVE_POLLS: Final = 2

API_BASE_URL: Final = "https://api2.tigoenergy.com/api/v3"

ATTR_LATEST_STABLE_TIMESTAMP: Final = "latest_stable_timestamp"
ATTR_IS_STALE: Final = "is_stale"
ATTR_DATA_LAG_SECONDS: Final = "data_lag_seconds"
ATTR_TELEMETRY_LAG_STATUS: Final = "telemetry_lag_status"
ATTR_LAG_WARNING_MINUTES: Final = "lag_warning_minutes"
ATTR_LAG_CRITICAL_MINUTES: Final = "lag_critical_minutes"
ATTR_TELEMETRY_LAG_STATUS_RAW: Final = "telemetry_lag_status_raw"
ATTR_TELEMETRY_LAG_GUARD_ACTIVE: Final = "telemetry_lag_guard_active"
ATTR_TELEMETRY_LAG_GUARD_REASON: Final = "telemetry_lag_guard_reason"
ATTR_LATEST_SOURCE_CHECKIN: Final = "latest_source_checkin"
ATTR_LATEST_NON_EMPTY_TELEMETRY_TIMESTAMP: Final = "latest_non_empty_telemetry_timestamp"
ATTR_LATEST_POSITIVE_TELEMETRY_TIMESTAMP: Final = "latest_positive_telemetry_timestamp"
ATTR_POSITIVE_PRODUCTION_AGE_MINUTES: Final = "positive_production_age_minutes"
ATTR_SUN_STATE: Final = "sun_state"
ATTR_SUN_ELEVATION: Final = "sun_elevation"
ATTR_SYSTEM_DATA_TIMESTAMP: Final = "system_data_timestamp"
ATTR_SYSTEM_DATA_AGE_SECONDS: Final = "system_data_age_seconds"
ATTR_SYSTEM_DATA_IS_STALE: Final = "system_data_is_stale"
ATTR_MODULE_DATA_TIMESTAMP: Final = "module_data_timestamp"
ATTR_MODULE_DATA_AGE_SECONDS: Final = "module_data_age_seconds"
ATTR_MODULE_DATA_IS_STALE: Final = "module_data_is_stale"
ATTR_ALERTS_SUPPORTED: Final = "alerts_supported"
ATTR_LATEST_ALERT_ID: Final = "latest_alert_id"
ATTR_LATEST_ALERT_UNIQUE_ID: Final = "latest_alert_unique_id"
ATTR_LATEST_ALERT_MESSAGE: Final = "latest_alert_message"
ATTR_LATEST_ALERT_DESCRIPTION_HTML: Final = "latest_alert_description_html"
ATTR_LATEST_ALERT_ARCHIVED: Final = "latest_alert_archived"
