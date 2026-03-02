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
    async_setup_entry,
)
from custom_components.tigo_energy.api import TigoApiAuthError, TigoApiConnectionError
from custom_components.tigo_energy.const import (
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    DOMAIN,
    ENTRY_MODE_SINGLE_SYSTEM,
    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
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
