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
                    "low_rssi_module_count": module_data.low_rssi_module_count,
                    "watch_rssi_module_count": module_data.watch_rssi_module_count,
                    "worst_rssi": module_data.worst_rssi,
                }
                if module_data
                else None
            ),
            "system_count": len(summary_data.systems),
        }

    return diagnostics
