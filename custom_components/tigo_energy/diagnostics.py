"""Diagnostics support for Tigo Energy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD
from .models import TigoRuntimeData

REDACT_KEYS = {CONF_PASSWORD, "auth", "token", "bearer", "Authorization"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime: TigoRuntimeData | None = entry.runtime_data

    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": dict(entry.options),
    }

    if runtime is not None:
        summary_data = runtime.summary_coordinator.data
        module_data = runtime.module_coordinator.data if runtime.module_coordinator else None

        diagnostics["runtime"] = {
            "entry_mode": runtime.entry_mode,
            "account_id": runtime.account_id,
            "tracked_system_ids": sorted(runtime.tracked_system_ids),
            "system_subentry_ids": {
                str(system_id): subentry_id
                for system_id, subentry_id in runtime.system_subentry_ids.items()
            },
            "summary_freshness": {
                "latest_stable_timestamp": summary_data.freshness.latest_stable_timestamp,
                "fetched_at": summary_data.freshness.fetched_at,
                "lag_seconds": summary_data.freshness.lag_seconds,
                "is_stale": summary_data.freshness.is_stale,
            },
            "module_freshness": (
                {
                    "latest_stable_timestamp": module_data.freshness.latest_stable_timestamp,
                    "fetched_at": module_data.freshness.fetched_at,
                    "lag_seconds": module_data.freshness.lag_seconds,
                    "is_stale": module_data.freshness.is_stale,
                    "dedupe_ignored_points": module_data.dedupe_ignored_points,
                    "empty_window_fallback_attempts": module_data.empty_window_fallback_attempts,
                    "empty_window_fallback_hits": module_data.empty_window_fallback_hits,
                    "future_rows_dropped": module_data.future_rows_dropped,
                    "invalid_timestamp_rows": module_data.invalid_timestamp_rows,
                    "low_rssi_module_count": module_data.low_rssi_module_count,
                    "watch_rssi_module_count": module_data.watch_rssi_module_count,
                    "worst_rssi": module_data.worst_rssi,
                }
                if module_data
                else None
            ),
            "systems": {
                str(system_id): {
                    "name": system.name,
                    "timezone": system.timezone,
                    "system_data_timestamp": system.freshest_timestamp,
                    "system_data_age_seconds": system.system_data_age_seconds,
                    "system_data_is_stale": system.system_data_is_stale,
                    "latest_source_checkin": system.latest_source_checkin,
                    "latest_non_empty_telemetry_timestamp": (
                        system.latest_non_empty_telemetry_timestamp
                    ),
                    "heartbeat_age_seconds": system.heartbeat_age_seconds,
                    "telemetry_lag_seconds": system.telemetry_lag_seconds,
                    "telemetry_lag_status": system.telemetry_lag_status,
                    "system_status": system.system_status,
                    "recent_alert_count": system.recent_alert_count,
                    "has_monitored_modules": system.has_monitored_modules,
                    "alerts": {
                        "alerts_supported": system.alert_state.alerts_supported,
                        "active_alert_count": system.alert_state.active_count,
                        "pv_off_active": system.alert_state.pv_off_active,
                        "string_shutdown_active": system.alert_state.string_shutdown_active,
                        "latest_active_alert": (
                            {
                                "alert_id": (
                                    system.alert_state.latest_active_alert.alert_id
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                                "unique_id": (
                                    system.alert_state.latest_active_alert.unique_id
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                                "title": (
                                    system.alert_state.latest_active_alert.title
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                                "generated": (
                                    system.alert_state.latest_active_alert.generated
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                                "added": (
                                    system.alert_state.latest_active_alert.added
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                                "archived": (
                                    system.alert_state.latest_active_alert.archived
                                    if system.alert_state.latest_active_alert
                                    else None
                                ),
                            }
                            if system.alert_state.latest_active_alert
                            else None
                        ),
                    },
                    "module_label_map_count": len(system.module_label_map),
                    "array_count": len(system.arrays),
                    "module_array_map_count": len(system.module_array_map),
                    "arrays": {
                        array_id: {
                            "name": array.name,
                            "short_label": array.short_label,
                            "string_id": array.string_id,
                            "mppt_label": array.mppt_label,
                            "inverter_label": array.inverter_label,
                            "panel_count": len(array.panel_labels),
                        }
                        for array_id, array in system.arrays.items()
                    },
                }
                for system_id, system in summary_data.systems.items()
            },
            "system_count": len(summary_data.systems),
        }

    return diagnostics
