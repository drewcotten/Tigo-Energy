"""Tests for Tigo diagnostics output."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.const import DOMAIN
from custom_components.tigo_energy.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_username_password_and_email(hass):
    """Diagnostics should redact user PII/secrets from entry data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "super-secret",
            "email": "user@example.com",
            "account_id": "123",
        },
        options={},
        entry_id="diag-entry",
    )
    entry.add_to_hass(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    redacted_entry = diagnostics["entry"]

    assert redacted_entry[CONF_USERNAME] == "**REDACTED**"
    assert redacted_entry[CONF_PASSWORD] == "**REDACTED**"
    assert redacted_entry["email"] == "**REDACTED**"
    assert redacted_entry["account_id"] == "123"
