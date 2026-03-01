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
                    "latest_source_checkin": system.latest_source_checkin,
                    "latest_non_empty_telemetry_timestamp": (
                        system.latest_non_empty_telemetry_timestamp
                    ),
                    "heartbeat_age_seconds": system.heartbeat_age_seconds,
                    "telemetry_lag_seconds": system.telemetry_lag_seconds,
                    "telemetry_lag_status": system.telemetry_lag_status,
                }
                for system_id, system in summary_data.systems.items()
            },
            "system_count": len(summary_data.systems),
        }

    return diagnostics
