"""Tests for Tigo Energy config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.config_flow import (
    FlowSystemRecord,
    InvalidAuth,
    ValidationResult,
)
from custom_components.tigo_energy.const import (
    CONF_ACCOUNT_ID,
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    DOMAIN,
    ENTRY_MODE_ALL_SYSTEMS,
    ENTRY_MODE_SINGLE_SYSTEM,
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
    OPT_SUMMARY_POLL_SECONDS,
    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    SUBENTRY_TYPE_SYSTEM,
)


async def test_config_flow_single_system_success(hass):
    """Test user -> scope -> system select happy path."""
    validation = ValidationResult(
        account_id="42",
        systems=[FlowSystemRecord(system_id=1001, name="Site One")],
    )

    with patch(
        "custom_components.tigo_energy.config_flow._async_validate_credentials",
        AsyncMock(return_value=validation),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "scope"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ENTRY_MODE: ENTRY_MODE_SINGLE_SYSTEM},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "system_select"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SYSTEM_ID: "1001"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "module_telemetry"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                OPT_SUMMARY_POLL_SECONDS: 60,
                OPT_MODULE_POLL_SECONDS: 300,
                OPT_ENABLE_ARRAY_TELEMETRY: True,
                OPT_ENABLE_PANEL_TELEMETRY: True,
                OPT_ENABLE_PERSISTENT_NOTIFICATIONS: True,
                OPT_NOTIFY_CONNECTION_ISSUES: True,
                OPT_NOTIFY_LOW_RSSI: False,
                OPT_NOTIFY_TELEMETRY_LAG: False,
                OPT_NOTIFY_PV_OFF: True,
                OPT_NOTIFY_STRING_SHUTDOWN: True,
                OPT_NOTIFY_ACTIVE_ALERT_SUMMARY: False,
                OPT_ENABLE_SUNSET_ALERT_GUARD: True,
                OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: 3.0,
                OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: 90,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTRY_MODE] == ENTRY_MODE_SINGLE_SYSTEM
    assert result["data"][CONF_ACCOUNT_ID] == "42"
    assert len(result["subentries"]) == 1
    subentry = result["subentries"][0]
    assert subentry["subentry_type"] == SUBENTRY_TYPE_SYSTEM
    assert subentry["title"] == "Site One"
    assert subentry["unique_id"] == "1001"
    assert subentry["data"]["system_id"] == 1001
    assert result["options"][OPT_SUMMARY_POLL_SECONDS] == 60
    assert result["options"][OPT_MODULE_POLL_SECONDS] == 300
    assert result["options"][OPT_ENABLE_ARRAY_TELEMETRY] is True
    assert result["options"][OPT_ENABLE_PANEL_TELEMETRY] is True
    assert result["options"][OPT_ENABLE_MODULE_TELEMETRY] is True
    assert result["options"][OPT_ENABLE_PERSISTENT_NOTIFICATIONS] is True
    assert result["options"][OPT_NOTIFY_CONNECTION_ISSUES] is True
    assert result["options"][OPT_NOTIFY_LOW_RSSI] is False
    assert result["options"][OPT_NOTIFY_TELEMETRY_LAG] is False
    assert result["options"][OPT_NOTIFY_PV_OFF] is True
    assert result["options"][OPT_NOTIFY_STRING_SHUTDOWN] is True
    assert result["options"][OPT_NOTIFY_ACTIVE_ALERT_SUMMARY] is False
    assert result["options"][OPT_ENABLE_SUNSET_ALERT_GUARD] is True
    assert result["options"][OPT_SUN_GUARD_MIN_ELEVATION_DEGREES] == 3.0
    assert result["options"][OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES] == 90
    assert result["options"][OPT_ENABLE_ALERT_FEED_NOTIFICATIONS] is True


async def test_config_flow_all_systems_success(hass):
    """Test user -> scope all systems path."""
    validation = ValidationResult(
        account_id="42",
        systems=[
            FlowSystemRecord(system_id=1001, name="Site One"),
            FlowSystemRecord(system_id=1002, name="Site Two"),
        ],
    )

    with patch(
        "custom_components.tigo_energy.config_flow._async_validate_credentials",
        AsyncMock(return_value=validation),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ENTRY_MODE: ENTRY_MODE_ALL_SYSTEMS},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "module_telemetry"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                OPT_SUMMARY_POLL_SECONDS: 75,
                OPT_MODULE_POLL_SECONDS: 360,
                OPT_ENABLE_ARRAY_TELEMETRY: False,
                OPT_ENABLE_PANEL_TELEMETRY: False,
                OPT_ENABLE_PERSISTENT_NOTIFICATIONS: False,
                OPT_NOTIFY_CONNECTION_ISSUES: False,
                OPT_NOTIFY_LOW_RSSI: False,
                OPT_NOTIFY_TELEMETRY_LAG: False,
                OPT_NOTIFY_PV_OFF: False,
                OPT_NOTIFY_STRING_SHUTDOWN: False,
                OPT_NOTIFY_ACTIVE_ALERT_SUMMARY: False,
                OPT_ENABLE_SUNSET_ALERT_GUARD: False,
                OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: -1.0,
                OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: 120,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTRY_MODE] == ENTRY_MODE_ALL_SYSTEMS
    assert {subentry["data"]["system_id"] for subentry in result["subentries"]} == {
        1001,
        1002,
    }
    assert result["options"][OPT_SUMMARY_POLL_SECONDS] == 75
    assert result["options"][OPT_MODULE_POLL_SECONDS] == 360
    assert result["options"][OPT_ENABLE_ARRAY_TELEMETRY] is False
    assert result["options"][OPT_ENABLE_PANEL_TELEMETRY] is False
    assert result["options"][OPT_ENABLE_MODULE_TELEMETRY] is False
    assert result["options"][OPT_ENABLE_PERSISTENT_NOTIFICATIONS] is False
    assert result["options"][OPT_NOTIFY_CONNECTION_ISSUES] is False
    assert result["options"][OPT_NOTIFY_LOW_RSSI] is False
    assert result["options"][OPT_NOTIFY_TELEMETRY_LAG] is False
    assert result["options"][OPT_NOTIFY_PV_OFF] is False
    assert result["options"][OPT_NOTIFY_STRING_SHUTDOWN] is False
    assert result["options"][OPT_NOTIFY_ACTIVE_ALERT_SUMMARY] is False
    assert result["options"][OPT_ENABLE_SUNSET_ALERT_GUARD] is False
    assert result["options"][OPT_SUN_GUARD_MIN_ELEVATION_DEGREES] == -1.0
    assert result["options"][OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES] == 120
    assert result["options"][OPT_ENABLE_ALERT_FEED_NOTIFICATIONS] is False


async def test_config_flow_invalid_auth(hass):
    """Test auth error handling."""
    with patch(
        "custom_components.tigo_energy.config_flow._async_validate_credentials",
        AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "bad"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_reauth_success(hass):
    """Test successful reauth flow updates entry credentials."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo Energy",
        data={
            CONF_USERNAME: "old@example.com",
            CONF_PASSWORD: "oldpw",
            CONF_ACCOUNT_ID: "42",
            CONF_ENTRY_MODE: ENTRY_MODE_SINGLE_SYSTEM,
        },
        source=config_entries.SOURCE_USER,
        entry_id="test-entry",
        unique_id="42:1001",
    )
    entry.add_to_hass(hass)

    validation = ValidationResult(
        account_id="42",
        systems=[FlowSystemRecord(system_id=1001, name="Site One")],
    )

    with (
        patch(
            "custom_components.tigo_energy.config_flow._async_validate_credentials",
            AsyncMock(return_value=validation),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "new@example.com", CONF_PASSWORD: "newpw"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

    updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_USERNAME] == "new@example.com"
    assert updated_entry.data[CONF_PASSWORD] == "newpw"
