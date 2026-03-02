"""Tests for integration setup lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy import (
    _async_migrate_module_ids_to_semantic_labels,
    _async_remove_panel_entities_and_devices,
    _configured_system_subentry_ids,
    _legacy_configured_system_ids,
    _merged_options,
    async_setup_entry,
)
from custom_components.tigo_energy.api import TigoApiAuthError, TigoApiConnectionError
from custom_components.tigo_energy.const import (
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    CONF_SYSTEM_IDS,
    DOMAIN,
    ENTRY_MODE_ALL_SYSTEMS,
    ENTRY_MODE_SINGLE_SYSTEM,
    OPT_ENABLE_ARRAY_TELEMETRY,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_ENABLE_PANEL_TELEMETRY,
    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
    SUBENTRY_TYPE_SYSTEM,
)


async def test_setup_entry_auth_error_raises_auth_failed(hass):
    """Startup invalid auth should trigger ConfigEntryAuthFailed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_ENTRY_MODE: ENTRY_MODE_SINGLE_SYSTEM,
            CONF_SYSTEM_ID: 1001,
        },
        options={OPT_ENABLE_PERSISTENT_NOTIFICATIONS: False},
        entry_id="entry-auth",
    )
    entry.add_to_hass(hass)

    mock_client = AsyncMock()
    mock_client.async_login.side_effect = TigoApiAuthError("bad credentials")

    with (
        patch("custom_components.tigo_energy.TigoApiClient", return_value=mock_client),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_entry_connection_error_raises_not_ready(hass):
    """Startup connectivity issues should still use ConfigEntryNotReady."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_ENTRY_MODE: ENTRY_MODE_SINGLE_SYSTEM,
            CONF_SYSTEM_ID: 1001,
        },
        options={OPT_ENABLE_PERSISTENT_NOTIFICATIONS: False},
        entry_id="entry-conn",
    )
    entry.add_to_hass(hass)

    mock_client = AsyncMock()
    mock_client.async_login.side_effect = TigoApiConnectionError("offline")

    with (
        patch("custom_components.tigo_energy.TigoApiClient", return_value=mock_client),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


async def test_module_registry_migration_updates_entity_and_device_ids(hass):
    """Module migration should rewrite entity unique_id and device identifiers."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        entry_id="entry-migrate",
    )
    entry.add_to_hass(hass)

    fake_entity = SimpleNamespace(
        unique_id=f"{entry.entry_id}_module_1001_89287797_Pin",
        domain="sensor",
        platform=DOMAIN,
        entity_id="sensor.tigo_module_89287797_pin",
        device_id="device-1",
    )

    fake_device = SimpleNamespace(
        id="device-1",
        identifiers={(DOMAIN, "module_1001_89287797")},
    )

    fake_entity_registry = SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: None,
        async_update_entity=Mock(),
    )
    fake_device_registry = SimpleNamespace(
        async_get=lambda device_id: fake_device if device_id == "device-1" else None,
        async_get_device=lambda identifiers: None,
        async_update_device=Mock(),
    )

    with (
        patch("custom_components.tigo_energy.er.async_get", return_value=fake_entity_registry),
        patch(
            "custom_components.tigo_energy.er.async_entries_for_config_entry",
            return_value=[fake_entity],
        ),
        patch("custom_components.tigo_energy.dr.async_get", return_value=fake_device_registry),
    ):
        await _async_migrate_module_ids_to_semantic_labels(
            hass=hass,
            entry=entry,
            module_label_map_by_system={1001: {"89287797": "A1"}},
        )

    fake_entity_registry.async_update_entity.assert_called_once_with(
        "sensor.tigo_module_89287797_pin",
        new_unique_id=f"{entry.entry_id}_module_1001_A1_Pin",
    )
    fake_device_registry.async_update_device.assert_called_once_with(
        "device-1",
        new_identifiers={(DOMAIN, "module_1001_A1")},
    )


def test_configured_system_subentry_ids_filters_to_system_type() -> None:
    """System subentry mapping should include only valid system subentries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_id": "sub-1",
                "subentry_type": SUBENTRY_TYPE_SYSTEM,
                "title": "Site One",
                "unique_id": "1001",
                "data": {CONF_SYSTEM_ID: 1001},
            },
            {
                "subentry_id": "sub-x",
                "subentry_type": "other",
                "title": "Ignore",
                "unique_id": "x",
                "data": {CONF_SYSTEM_ID: 9999},
            },
        ],
    )

    assert _configured_system_subentry_ids(entry) == {1001: "sub-1"}


def test_legacy_configured_system_ids_handles_mixed_values() -> None:
    """Legacy system ID extraction should ignore invalid values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENTRY_MODE: ENTRY_MODE_ALL_SYSTEMS,
            CONF_SYSTEM_IDS: [1001, "1002", None, "bad"],
        },
    )

    assert _legacy_configured_system_ids(entry, ENTRY_MODE_ALL_SYSTEMS) == {1001, 1002}


def test_merged_options_maps_legacy_module_toggle_to_panel() -> None:
    """Legacy module toggle should map to panel toggle and keep arrays enabled by default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={OPT_ENABLE_MODULE_TELEMETRY: True},
    )

    options = _merged_options(entry)
    assert options[OPT_ENABLE_ARRAY_TELEMETRY] is True
    assert options[OPT_ENABLE_PANEL_TELEMETRY] is True
    assert options[OPT_ENABLE_MODULE_TELEMETRY] is True


def test_merged_options_prefers_new_panel_toggle_over_legacy() -> None:
    """New panel toggle should override legacy alias when both are present."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            OPT_ENABLE_MODULE_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: False,
            OPT_ENABLE_ARRAY_TELEMETRY: False,
        },
    )

    options = _merged_options(entry)
    assert options[OPT_ENABLE_ARRAY_TELEMETRY] is False
    assert options[OPT_ENABLE_PANEL_TELEMETRY] is False
    assert options[OPT_ENABLE_MODULE_TELEMETRY] is False


async def test_remove_panel_entities_and_devices_when_panel_telemetry_disabled(hass) -> None:
    """Panel cleanup should remove only panel entities and orphaned panel devices."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-panel-prune")
    entry.add_to_hass(hass)

    panel_entity = SimpleNamespace(
        unique_id=f"{entry.entry_id}_module_1001_A1_Pin",
        entity_id="sensor.site_panel_a1_input_power",
        device_id="dev-panel",
    )
    system_entity = SimpleNamespace(
        unique_id=f"{entry.entry_id}_system_1001_last_power_dc",
        entity_id="sensor.site_current_power",
        device_id="dev-system",
    )
    panel_device = SimpleNamespace(
        identifiers={(DOMAIN, "module_1001_A1")},
    )

    fake_entity_registry = SimpleNamespace(async_remove=Mock())
    fake_device_registry = SimpleNamespace(
        async_get=lambda device_id: panel_device if device_id == "dev-panel" else None,
        async_remove_device=Mock(),
    )

    with (
        patch("custom_components.tigo_energy.er.async_get", return_value=fake_entity_registry),
        patch(
            "custom_components.tigo_energy.er.async_entries_for_config_entry",
            side_effect=[[panel_entity, system_entity], [system_entity]],
        ),
        patch("custom_components.tigo_energy.dr.async_get", return_value=fake_device_registry),
    ):
        await _async_remove_panel_entities_and_devices(hass=hass, entry=entry)

    fake_entity_registry.async_remove.assert_called_once_with(
        "sensor.site_panel_a1_input_power"
    )
    fake_device_registry.async_remove_device.assert_called_once_with("dev-panel")
