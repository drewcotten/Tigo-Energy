"""Constants for the Tigo Energy integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "tigo_energy"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

MANUFACTURER: Final = "Tigo Energy"

CONF_ENTRY_MODE: Final = "entry_mode"
CONF_SYSTEM_ID: Final = "system_id"
CONF_SYSTEM_IDS: Final = "system_ids"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"

ENTRY_MODE_SINGLE_SYSTEM: Final = "single_system"
ENTRY_MODE_ALL_SYSTEMS: Final = "all_systems"

OPT_SUMMARY_POLL_SECONDS: Final = "summary_poll_seconds"
OPT_MODULE_POLL_SECONDS: Final = "module_poll_seconds"
OPT_ENABLE_MODULE_TELEMETRY: Final = "enable_module_telemetry"
OPT_STALE_THRESHOLD_SECONDS: Final = "stale_threshold_seconds"
OPT_BACKFILL_WINDOW_MINUTES: Final = "backfill_window_minutes"
OPT_RECENT_CUTOFF_MINUTES: Final = "recent_cutoff_minutes"
OPT_RSSI_WATCH_THRESHOLD: Final = "rssi_watch_threshold"
OPT_RSSI_ALERT_THRESHOLD: Final = "rssi_alert_threshold"
OPT_RSSI_ALERT_CONSECUTIVE_POLLS: Final = "rssi_alert_consecutive_polls"

DEFAULT_SUMMARY_POLL_SECONDS: Final = 60
DEFAULT_MODULE_POLL_SECONDS: Final = 300
DEFAULT_ENABLE_MODULE_TELEMETRY: Final = False
DEFAULT_STALE_THRESHOLD_SECONDS: Final = 3600
DEFAULT_BACKFILL_WINDOW_MINUTES: Final = 120
DEFAULT_RECENT_CUTOFF_MINUTES: Final = 20
DEFAULT_RSSI_WATCH_THRESHOLD: Final = 120
DEFAULT_RSSI_ALERT_THRESHOLD: Final = 80
DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 3

MIN_SUMMARY_POLL_SECONDS: Final = 15
MIN_MODULE_POLL_SECONDS: Final = 30
MIN_STALE_THRESHOLD_SECONDS: Final = 300
MIN_BACKFILL_WINDOW_MINUTES: Final = 30
MIN_RECENT_CUTOFF_MINUTES: Final = 5
MIN_RSSI_THRESHOLD: Final = 0
MIN_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 1

MAX_POLL_SECONDS: Final = 3600
MAX_STALE_THRESHOLD_SECONDS: Final = 21600
MAX_BACKFILL_WINDOW_MINUTES: Final = 360
MAX_RECENT_CUTOFF_MINUTES: Final = 60
MAX_RSSI_THRESHOLD: Final = 255
MAX_RSSI_ALERT_CONSECUTIVE_POLLS: Final = 20

API_BASE_URL: Final = "https://api2.tigoenergy.com/api/v3"

ATTR_LATEST_STABLE_TIMESTAMP: Final = "latest_stable_timestamp"
ATTR_IS_STALE: Final = "is_stale"
ATTR_DATA_LAG_SECONDS: Final = "data_lag_seconds"
