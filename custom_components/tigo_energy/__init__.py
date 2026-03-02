"""The Tigo Energy integration."""

from __future__ import annotations

import logging
import re
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .api import TigoApiAuthError, TigoApiClient, TigoApiConnectionError, TigoAuthCredentials
from .const import (
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    CONF_SYSTEM_IDS,
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    DEFAULT_ENABLE_ARRAY_TELEMETRY,
    DEFAULT_ENABLE_MODULE_TELEMETRY,
    DEFAULT_ENABLE_PANEL_TELEMETRY,
    DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
    DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_NOTIFY_ACTIVE_ALERT_SUMMARY,
    DEFAULT_NOTIFY_CONNECTION_ISSUES,
    DEFAULT_NOTIFY_LOW_RSSI,
    DEFAULT_NOTIFY_PV_OFF,
    DEFAULT_NOTIFY_STRING_SHUTDOWN,
    DEFAULT_NOTIFY_TELEMETRY_LAG,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    DOMAIN,
    ENTRY_MODE_ALL_SYSTEMS,
    ENTRY_MODE_SINGLE_SYSTEM,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    OPT_ENABLE_ARRAY_TELEMETRY,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_ENABLE_PANEL_TELEMETRY,
    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
    OPT_ENABLE_SUNSET_ALERT_GUARD,
    OPT_MODULE_POLL_SECONDS,
    OPT_NOTIFY_ACTIVE_ALERT_SUMMARY,
    OPT_NOTIFY_CONNECTION_ISSUES,
    OPT_NOTIFY_LOW_RSSI,
    OPT_NOTIFY_PV_OFF,
    OPT_NOTIFY_STRING_SHUTDOWN,
    OPT_NOTIFY_TELEMETRY_LAG,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    PLATFORMS,
    SUBENTRY_TYPE_SYSTEM,
)
from .coordinator import TigoModuleCoordinator, TigoSummaryCoordinator
from .models import TigoRuntimeData
from .notifications import CONNECTION_SOURCE_SETUP, TigoConnectionNotifier

type TigoConfigEntry = ConfigEntry[TigoRuntimeData]
LOGGER = logging.getLogger(__name__)
MODULE_UNIQUE_ID_PATTERN = re.compile(
    r"^(?P<system_id>\d+)_(?P<module_id>.+)_(?P<metric>Pin|Vin|Iin|RSSI)$"
)


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
    configured_system_ids = _configured_system_ids_from_subentries(entry)

    # Backward compatibility: convert legacy single/all system entry data into system subentries.
    if not configured_system_ids:
        legacy_system_ids = _legacy_configured_system_ids(entry, entry_mode)
        if legacy_system_ids:
            await _async_create_system_subentries_from_legacy(
                hass=hass,
                entry=entry,
                client=client,
                system_ids=legacy_system_ids,
            )
            configured_system_ids = _configured_system_ids_from_subentries(entry)
            if not configured_system_ids:
                configured_system_ids = legacy_system_ids

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
    if (
        entry_mode == ENTRY_MODE_ALL_SYSTEMS
        and not configured_system_ids
        and not entry.subentries
    ):
        # Keep a snapshot of system ids for all-systems entries.
        entry_data = {**entry.data, CONF_SYSTEM_IDS: sorted(tracked_system_ids)}
        hass.config_entries.async_update_entry(entry, data=entry_data)

    system_subentry_ids = _configured_system_subentry_ids(
        entry,
        allowed_system_ids=tracked_system_ids,
    )

    module_polling_required = bool(
        options[OPT_ENABLE_ARRAY_TELEMETRY] or options[OPT_ENABLE_PANEL_TELEMETRY]
    )

    module_coordinator = None
    if module_polling_required:
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
        system_subentry_ids=system_subentry_ids,
        connection_notifier=connection_notifier,
    )

    await _async_migrate_module_ids_to_semantic_labels(
        hass=hass,
        entry=entry,
        module_label_map_by_system=_module_label_map_by_system(summary_coordinator.data.systems),
    )
    if not options[OPT_ENABLE_PANEL_TELEMETRY]:
        await _async_remove_panel_entities_and_devices(hass=hass, entry=entry)

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
    legacy_panel_raw = entry.options.get(OPT_ENABLE_MODULE_TELEMETRY, DEFAULT_ENABLE_MODULE_TELEMETRY)
    legacy_panel_enabled = bool(legacy_panel_raw)
    panel_telemetry_enabled = bool(
        entry.options.get(
            OPT_ENABLE_PANEL_TELEMETRY,
            legacy_panel_enabled if legacy_panel_raw is not None else DEFAULT_ENABLE_PANEL_TELEMETRY,
        )
    )
    array_telemetry_enabled = bool(
        entry.options.get(
            OPT_ENABLE_ARRAY_TELEMETRY,
            DEFAULT_ENABLE_ARRAY_TELEMETRY,
        )
    )
    legacy_alert_feed_raw = entry.options.get(OPT_ENABLE_ALERT_FEED_NOTIFICATIONS)
    legacy_alert_feed_enabled = (
        bool(legacy_alert_feed_raw) if legacy_alert_feed_raw is not None else None
    )
    return {
        OPT_SUMMARY_POLL_SECONDS: int(
            entry.options.get(OPT_SUMMARY_POLL_SECONDS, DEFAULT_SUMMARY_POLL_SECONDS)
        ),
        OPT_MODULE_POLL_SECONDS: int(
            entry.options.get(OPT_MODULE_POLL_SECONDS, DEFAULT_MODULE_POLL_SECONDS)
        ),
        OPT_ENABLE_ARRAY_TELEMETRY: array_telemetry_enabled,
        OPT_ENABLE_PANEL_TELEMETRY: panel_telemetry_enabled,
        OPT_ENABLE_MODULE_TELEMETRY: panel_telemetry_enabled,
        OPT_ENABLE_PERSISTENT_NOTIFICATIONS: bool(
            entry.options.get(
                OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
                DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
            )
        ),
        OPT_NOTIFY_CONNECTION_ISSUES: bool(
            entry.options.get(
                OPT_NOTIFY_CONNECTION_ISSUES,
                DEFAULT_NOTIFY_CONNECTION_ISSUES,
            )
        ),
        OPT_NOTIFY_LOW_RSSI: bool(
            entry.options.get(
                OPT_NOTIFY_LOW_RSSI,
                DEFAULT_NOTIFY_LOW_RSSI,
            )
        ),
        OPT_NOTIFY_TELEMETRY_LAG: bool(
            entry.options.get(
                OPT_NOTIFY_TELEMETRY_LAG,
                DEFAULT_NOTIFY_TELEMETRY_LAG,
            )
        ),
        OPT_NOTIFY_PV_OFF: bool(
            entry.options.get(
                OPT_NOTIFY_PV_OFF,
                (
                    legacy_alert_feed_enabled
                    if legacy_alert_feed_enabled is not None
                    else DEFAULT_NOTIFY_PV_OFF
                ),
            )
        ),
        OPT_NOTIFY_STRING_SHUTDOWN: bool(
            entry.options.get(
                OPT_NOTIFY_STRING_SHUTDOWN,
                (
                    legacy_alert_feed_enabled
                    if legacy_alert_feed_enabled is not None
                    else DEFAULT_NOTIFY_STRING_SHUTDOWN
                ),
            )
        ),
        OPT_NOTIFY_ACTIVE_ALERT_SUMMARY: bool(
            entry.options.get(
                OPT_NOTIFY_ACTIVE_ALERT_SUMMARY,
                (
                    legacy_alert_feed_enabled
                    if legacy_alert_feed_enabled is not None
                    else DEFAULT_NOTIFY_ACTIVE_ALERT_SUMMARY
                ),
            )
        ),
        OPT_ENABLE_SUNSET_ALERT_GUARD: bool(
            entry.options.get(
                OPT_ENABLE_SUNSET_ALERT_GUARD,
                DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
            )
        ),
        OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: float(
            entry.options.get(
                OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES,
            )
        ),
        OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: int(
            entry.options.get(
                OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
            )
        ),
        OPT_ENABLE_ALERT_FEED_NOTIFICATIONS: bool(
            entry.options.get(
                OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
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


async def _async_remove_panel_entities_and_devices(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove panel entities/devices when panel telemetry is disabled."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    panel_unique_prefix = f"{entry.entry_id}_module_"

    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    panel_entity_ids: list[str] = []
    panel_device_ids: set[str] = set()

    for entity_entry in entity_entries:
        unique_id = entity_entry.unique_id or ""
        if not unique_id.startswith(panel_unique_prefix):
            continue
        panel_entity_ids.append(entity_entry.entity_id)
        if entity_entry.device_id:
            panel_device_ids.add(entity_entry.device_id)

    for entity_id in panel_entity_ids:
        entity_registry.async_remove(entity_id)

    if not panel_device_ids:
        return

    remaining_entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    remaining_device_ids = {
        entity_entry.device_id
        for entity_entry in remaining_entities
        if entity_entry.device_id
    }

    for device_id in panel_device_ids:
        if device_id in remaining_device_ids:
            continue
        device_entry = device_registry.async_get(device_id)
        if device_entry is None:
            continue
        if not any(
            domain == DOMAIN and str(identifier).startswith("module_")
            for domain, identifier in device_entry.identifiers
        ):
            continue
        device_registry.async_remove_device(device_id)


def _configured_system_subentry_ids(
    entry: ConfigEntry,
    *,
    allowed_system_ids: set[int] | None = None,
) -> dict[int, str]:
    """Return system_id -> subentry_id mapping for configured system subentries."""
    mapping: dict[int, str] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_SYSTEM:
            continue
        raw_system_id = subentry.data.get(CONF_SYSTEM_ID)
        if raw_system_id is None:
            continue
        try:
            system_id = int(raw_system_id)
        except (TypeError, ValueError):
            continue
        if allowed_system_ids is not None and system_id not in allowed_system_ids:
            continue
        mapping[system_id] = subentry.subentry_id
    return mapping


def _configured_system_ids_from_subentries(entry: ConfigEntry) -> set[int]:
    """Return configured system IDs from system subentries."""
    return set(_configured_system_subentry_ids(entry).keys())


def _legacy_configured_system_ids(entry: ConfigEntry, entry_mode: str) -> set[int]:
    """Return configured system IDs from legacy entry data fields."""
    if entry_mode == ENTRY_MODE_SINGLE_SYSTEM and CONF_SYSTEM_ID in entry.data:
        try:
            return {int(entry.data[CONF_SYSTEM_ID])}
        except (TypeError, ValueError):
            return set()

    configured: set[int] = set()
    for system_id in entry.data.get(CONF_SYSTEM_IDS, []):
        if system_id is None:
            continue
        try:
            configured.add(int(system_id))
        except (TypeError, ValueError):
            continue
    return configured


async def _async_create_system_subentries_from_legacy(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: TigoApiClient,
    system_ids: set[int],
) -> None:
    """Create system subentries for legacy entries that stored systems in entry data."""
    if not system_ids:
        return

    system_names: dict[int, str] = {}
    try:
        list_payload = await client.async_list_systems()
    except Exception as err:  # pragma: no cover - defensive fallback
        LOGGER.debug("Unable to fetch system names for legacy subentry migration: %s", err)
    else:
        system_names = {
            int(record["system_id"]): str(
                record.get("name") or f"System {record['system_id']}"
            )
            for record in list_payload
            if record.get("system_id") is not None
        }

    existing_ids = _configured_system_ids_from_subentries(entry)
    for system_id in sorted(system_ids):
        if system_id in existing_ids:
            continue

        subentry = ConfigSubentry(
            subentry_type=SUBENTRY_TYPE_SYSTEM,
            unique_id=str(system_id),
            title=system_names.get(system_id, f"System {system_id}"),
            data=MappingProxyType({CONF_SYSTEM_ID: system_id}),
        )
        try:
            hass.config_entries.async_add_subentry(entry, subentry)
        except ValueError as err:
            LOGGER.debug(
                "Skipping legacy system subentry migration for %s due to conflict: %s",
                system_id,
                err,
            )


def _module_label_map_by_system(
    systems: dict[int, Any],
) -> dict[int, dict[str, str]]:
    """Return per-system raw module id => semantic label mappings."""
    result: dict[int, dict[str, str]] = {}
    for system_id, system in systems.items():
        labels = {
            raw_id: label
            for raw_id, label in system.module_label_map.items()
            if raw_id and label and raw_id != label
        }
        if labels:
            result[system_id] = labels
    return result


async def _async_migrate_module_ids_to_semantic_labels(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    module_label_map_by_system: dict[int, dict[str, str]],
) -> None:
    """Migrate module entity/device registry identifiers to semantic labels."""
    if not module_label_map_by_system:
        return

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    device_id_renames: dict[str, set[tuple[str, str]]] = {}
    for entity_entry in entity_entries:
        unique_id = entity_entry.unique_id or ""
        prefix = f"{entry.entry_id}_module_"
        if not unique_id.startswith(prefix):
            continue

        suffix = unique_id[len(prefix) :]
        match = MODULE_UNIQUE_ID_PATTERN.match(suffix)
        if match is None:
            continue

        system_id = int(match.group("system_id"))
        raw_module_id = match.group("module_id")
        metric = match.group("metric")
        label_map = module_label_map_by_system.get(system_id, {})
        semantic_module_id = label_map.get(raw_module_id)
        if semantic_module_id is None or semantic_module_id == raw_module_id:
            continue

        new_unique_id = (
            f"{entry.entry_id}_module_{system_id}_{semantic_module_id}_{metric}"
        )
        existing_entity_id = entity_registry.async_get_entity_id(
            entity_entry.domain,
            entity_entry.platform,
            new_unique_id,
        )
        if existing_entity_id and existing_entity_id != entity_entry.entity_id:
            LOGGER.warning(
                "Skipping module unique_id migration for %s due to conflict with %s",
                entity_entry.entity_id,
                existing_entity_id,
            )
            continue

        entity_registry.async_update_entity(
            entity_entry.entity_id,
            new_unique_id=new_unique_id,
        )
        LOGGER.debug(
            "Migrated module entity unique_id for %s: %s -> %s",
            entity_entry.entity_id,
            unique_id,
            new_unique_id,
        )

        if entity_entry.device_id:
            device_id_renames.setdefault(entity_entry.device_id, set()).add(
                (f"module_{system_id}_{raw_module_id}", f"module_{system_id}_{semantic_module_id}")
            )

    for device_id, renames in device_id_renames.items():
        device_entry = device_registry.async_get(device_id)
        if device_entry is None:
            continue
        identifiers = set(device_entry.identifiers)
        updated = False
        for old_id, new_id in renames:
            old_identifier = (DOMAIN, old_id)
            new_identifier = (DOMAIN, new_id)
            if old_identifier not in identifiers:
                continue
            existing_device = device_registry.async_get_device(identifiers={new_identifier})
            if existing_device and existing_device.id != device_id:
                LOGGER.warning(
                    "Skipping module device identifier migration for %s due to conflict on %s",
                    device_id,
                    new_identifier,
                )
                continue
            identifiers.discard(old_identifier)
            identifiers.add(new_identifier)
            updated = True

        if updated:
            device_registry.async_update_device(device_id, new_identifiers=identifiers)
