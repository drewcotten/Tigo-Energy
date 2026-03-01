"""Tests for integration setup lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy import async_setup_entry
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
