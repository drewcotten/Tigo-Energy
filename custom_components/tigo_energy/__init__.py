"""The Tigo Energy integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import TigoApiAuthError, TigoApiClient, TigoApiConnectionError, TigoAuthCredentials
from .const import (
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    CONF_SYSTEM_IDS,
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_ENABLE_MODULE_TELEMETRY,
    DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    ENTRY_MODE_SINGLE_SYSTEM,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
    OPT_MODULE_POLL_SECONDS,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
    PLATFORMS,
)
from .coordinator import TigoModuleCoordinator, TigoSummaryCoordinator
from .models import TigoRuntimeData
from .notifications import CONNECTION_SOURCE_SETUP, TigoConnectionNotifier

type TigoConfigEntry = ConfigEntry[TigoRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration from YAML (unused)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TigoConfigEntry) -> bool:
    """Set up Tigo Energy from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    options = _merged_options(entry)
    connection_notifier = (
        TigoConnectionNotifier(hass, entry.entry_id, entry.title)
        if options[OPT_ENABLE_PERSISTENT_NOTIFICATIONS]
        else None
    )

    client = TigoApiClient(
        hass=hass,
        credentials=TigoAuthCredentials(username=username, password=password),
    )

    try:
        await client.async_login()
    except TigoApiAuthError as err:
        if connection_notifier is not None:
            await connection_notifier.async_report_connection_recovered(CONNECTION_SOURCE_SETUP)
        raise ConfigEntryAuthFailed("Unable to authenticate with stored credentials") from err
    except TigoApiConnectionError as err:
        if connection_notifier is not None:
            await connection_notifier.async_report_connection_failure(CONNECTION_SOURCE_SETUP)
        raise ConfigEntryNotReady("Unable to connect to Tigo API") from err
    else:
        if connection_notifier is not None:
            await connection_notifier.async_report_connection_recovered(CONNECTION_SOURCE_SETUP)
    entry_mode = entry.data.get(CONF_ENTRY_MODE, ENTRY_MODE_SINGLE_SYSTEM)

    configured_system_ids: set[int] = set()
    if entry_mode == ENTRY_MODE_SINGLE_SYSTEM:
        configured_system_ids = {int(entry.data[CONF_SYSTEM_ID])}
    else:
        configured_system_ids = {int(system_id) for system_id in entry.data.get(CONF_SYSTEM_IDS, [])}

    summary_coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=client,
        entry_mode=entry_mode,
        configured_system_ids=configured_system_ids,
        options=options,
        connection_notifier=connection_notifier,
    )
    await summary_coordinator.async_config_entry_first_refresh()

    tracked_system_ids = set(summary_coordinator.data.systems)
    if entry_mode != ENTRY_MODE_SINGLE_SYSTEM and not configured_system_ids:
        # Keep a snapshot of system ids for all-systems entries.
        entry_data = {**entry.data, CONF_SYSTEM_IDS: sorted(tracked_system_ids)}
        hass.config_entries.async_update_entry(entry, data=entry_data)

    module_coordinator = None
    if options[OPT_ENABLE_MODULE_TELEMETRY]:
        module_coordinator = TigoModuleCoordinator(
            hass=hass,
            client=client,
            summary_coordinator=summary_coordinator,
            options=options,
            connection_notifier=connection_notifier,
        )
        await module_coordinator.async_config_entry_first_refresh()

    if connection_notifier is not None:
        await connection_notifier.async_clear()

    runtime_data = TigoRuntimeData(
        account_id=summary_coordinator.data.account_id,
        entry_mode=entry_mode,
        summary_coordinator=summary_coordinator,
        module_coordinator=module_coordinator,
        tracked_system_ids=tracked_system_ids,
        connection_notifier=connection_notifier,
    )
    runtime_data.unsub_update_listener = entry.add_update_listener(_async_options_updated)
    entry.runtime_data = runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TigoConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime_data = entry.runtime_data
    if runtime_data and runtime_data.connection_notifier is not None:
        await runtime_data.connection_notifier.async_clear()
    if runtime_data and callable(runtime_data.unsub_update_listener):
        runtime_data.unsub_update_listener()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: TigoConfigEntry) -> None:
    """Reload entry when options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def _merged_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return options merged with defaults."""
    return {
        OPT_SUMMARY_POLL_SECONDS: int(
            entry.options.get(OPT_SUMMARY_POLL_SECONDS, DEFAULT_SUMMARY_POLL_SECONDS)
        ),
        OPT_MODULE_POLL_SECONDS: int(
            entry.options.get(OPT_MODULE_POLL_SECONDS, DEFAULT_MODULE_POLL_SECONDS)
        ),
        OPT_ENABLE_MODULE_TELEMETRY: bool(
            entry.options.get(OPT_ENABLE_MODULE_TELEMETRY, DEFAULT_ENABLE_MODULE_TELEMETRY)
        ),
        OPT_ENABLE_PERSISTENT_NOTIFICATIONS: bool(
            entry.options.get(
                OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
                DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
            )
        ),
        OPT_STALE_THRESHOLD_SECONDS: int(
            entry.options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS)
        ),
        OPT_BACKFILL_WINDOW_MINUTES: int(
            entry.options.get(OPT_BACKFILL_WINDOW_MINUTES, DEFAULT_BACKFILL_WINDOW_MINUTES)
        ),
        OPT_RECENT_CUTOFF_MINUTES: int(
            entry.options.get(OPT_RECENT_CUTOFF_MINUTES, DEFAULT_RECENT_CUTOFF_MINUTES)
        ),
        OPT_RSSI_WATCH_THRESHOLD: int(
            entry.options.get(OPT_RSSI_WATCH_THRESHOLD, DEFAULT_RSSI_WATCH_THRESHOLD)
        ),
        OPT_RSSI_ALERT_THRESHOLD: int(
            entry.options.get(OPT_RSSI_ALERT_THRESHOLD, DEFAULT_RSSI_ALERT_THRESHOLD)
        ),
        OPT_RSSI_ALERT_CONSECUTIVE_POLLS: int(
            entry.options.get(
                OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
            )
        ),
    }
