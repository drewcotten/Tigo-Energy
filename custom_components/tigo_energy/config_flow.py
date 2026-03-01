"""Config flow for the Tigo Energy integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import TigoApiAuthError, TigoApiClient, TigoApiConnectionError, TigoAuthCredentials
from .const import (
    CONF_ACCOUNT_ID,
    CONF_ENTRY_MODE,
    CONF_SYSTEM_ID,
    CONF_SYSTEM_IDS,
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_ENABLE_MODULE_TELEMETRY,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    DOMAIN,
    ENTRY_MODE_ALL_SYSTEMS,
    ENTRY_MODE_SINGLE_SYSTEM,
    MAX_BACKFILL_WINDOW_MINUTES,
    MAX_POLL_SECONDS,
    MAX_RECENT_CUTOFF_MINUTES,
    MAX_RSSI_ALERT_CONSECUTIVE_POLLS,
    MAX_RSSI_THRESHOLD,
    MAX_STALE_THRESHOLD_SECONDS,
    MIN_BACKFILL_WINDOW_MINUTES,
    MIN_MODULE_POLL_SECONDS,
    MIN_RECENT_CUTOFF_MINUTES,
    MIN_RSSI_ALERT_CONSECUTIVE_POLLS,
    MIN_RSSI_THRESHOLD,
    MIN_STALE_THRESHOLD_SECONDS,
    MIN_SUMMARY_POLL_SECONDS,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_MODULE_POLL_SECONDS,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
)


@dataclass(slots=True)
class FlowSystemRecord:
    """Simple system record for config flow selections."""

    system_id: int
    name: str


class TigoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tigo Energy."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._account_id: str = ""
        self._systems: list[FlowSystemRecord] = []
        self._selected_entry_mode: str = ENTRY_MODE_SINGLE_SYSTEM
        self._selected_system_id: int | None = None
        self._enable_module_telemetry: bool = DEFAULT_ENABLE_MODULE_TELEMETRY
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Initial step with credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]

            try:
                validation = await _async_validate_credentials(
                    self.hass, self._username, self._password
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - defensive fallback
                errors["base"] = "unknown"
            else:
                self._account_id = validation.account_id
                self._systems = validation.systems
                if not self._systems:
                    errors["base"] = "no_systems"
                else:
                    return await self.async_step_scope()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_scope(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose whether this entry tracks one system or all systems."""
        if user_input is not None:
            entry_mode = user_input[CONF_ENTRY_MODE]
            self._selected_entry_mode = entry_mode
            if entry_mode == ENTRY_MODE_ALL_SYSTEMS:
                self._selected_system_id = None
                return await self.async_step_module_telemetry()

            return await self.async_step_system_select()

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTRY_MODE, default=ENTRY_MODE_SINGLE_SYSTEM): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=ENTRY_MODE_SINGLE_SYSTEM,
                                label="Single system",
                            ),
                            selector.SelectOptionDict(
                                value=ENTRY_MODE_ALL_SYSTEMS,
                                label="All systems",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="scope", data_schema=schema)

    async def async_step_system_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose one specific system."""
        errors: dict[str, str] = {}

        if user_input is not None:
            system_id = int(user_input[CONF_SYSTEM_ID])
            self._selected_entry_mode = ENTRY_MODE_SINGLE_SYSTEM
            self._selected_system_id = system_id
            return await self.async_step_module_telemetry()

        if not self._systems:
            errors["base"] = "no_systems"

        options = [
            selector.SelectOptionDict(
                value=str(record.system_id),
                label=f"{record.name} ({record.system_id})",
            )
            for record in self._systems
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_SYSTEM_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="system_select", data_schema=schema, errors=errors)

    async def async_step_module_telemetry(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose whether to enable module-level telemetry."""
        if user_input is not None:
            self._enable_module_telemetry = bool(user_input[OPT_ENABLE_MODULE_TELEMETRY])

            if self._selected_entry_mode == ENTRY_MODE_ALL_SYSTEMS:
                unique_id = f"{self._account_id}:all"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Tigo Energy (All Systems)",
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_ACCOUNT_ID: self._account_id,
                        CONF_ENTRY_MODE: ENTRY_MODE_ALL_SYSTEMS,
                        CONF_SYSTEM_IDS: [record.system_id for record in self._systems],
                    },
                    options={
                        OPT_ENABLE_MODULE_TELEMETRY: self._enable_module_telemetry,
                    },
                )

            if self._selected_system_id is None:
                return self.async_abort(reason="unknown")

            unique_id = f"{self._account_id}:{self._selected_system_id}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            selected_name = next(
                (
                    record.name
                    for record in self._systems
                    if record.system_id == self._selected_system_id
                ),
                f"System {self._selected_system_id}",
            )

            return self.async_create_entry(
                title=f"Tigo Energy ({selected_name})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_ACCOUNT_ID: self._account_id,
                    CONF_ENTRY_MODE: ENTRY_MODE_SINGLE_SYSTEM,
                    CONF_SYSTEM_ID: self._selected_system_id,
                },
                options={
                    OPT_ENABLE_MODULE_TELEMETRY: self._enable_module_telemetry,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_ENABLE_MODULE_TELEMETRY,
                    default=self._enable_module_telemetry,
                ): bool,
            }
        )
        return self.async_show_form(step_id="module_telemetry", data_schema=schema)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle initialization of reauthentication flow."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthentication by asking for fresh credentials."""
        errors: dict[str, str] = {}

        if self._reauth_entry is None:
            return self.async_abort(reason="unknown")

        default_username = self._reauth_entry.data.get(CONF_USERNAME, "")

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            try:
                validation = await _async_validate_credentials(self.hass, username, password)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover - defensive fallback
                errors["base"] = "unknown"
            else:
                existing_account = str(self._reauth_entry.data.get(CONF_ACCOUNT_ID, ""))
                if existing_account and validation.account_id != existing_account:
                    errors["base"] = "account_mismatch"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={
                            **self._reauth_entry.data,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password,
                            CONF_ACCOUNT_ID: validation.account_id,
                        },
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=default_username): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return options flow handler."""
        return TigoOptionsFlow(config_entry)


class TigoOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Tigo Energy."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            watch_threshold = int(user_input[OPT_RSSI_WATCH_THRESHOLD])
            alert_threshold = int(user_input[OPT_RSSI_ALERT_THRESHOLD])
            if watch_threshold <= alert_threshold:
                errors["base"] = "rssi_threshold_order"
            else:
                return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_SUMMARY_POLL_SECONDS,
                    default=int(options.get(OPT_SUMMARY_POLL_SECONDS, DEFAULT_SUMMARY_POLL_SECONDS)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SUMMARY_POLL_SECONDS, max=MAX_POLL_SECONDS)),
                vol.Required(
                    OPT_MODULE_POLL_SECONDS,
                    default=int(options.get(OPT_MODULE_POLL_SECONDS, DEFAULT_MODULE_POLL_SECONDS)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MODULE_POLL_SECONDS, max=MAX_POLL_SECONDS)),
                vol.Required(
                    OPT_ENABLE_MODULE_TELEMETRY,
                    default=bool(options.get(OPT_ENABLE_MODULE_TELEMETRY, DEFAULT_ENABLE_MODULE_TELEMETRY)),
                ): bool,
                vol.Required(
                    OPT_STALE_THRESHOLD_SECONDS,
                    default=int(
                        options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_STALE_THRESHOLD_SECONDS, max=MAX_STALE_THRESHOLD_SECONDS),
                ),
                vol.Required(
                    OPT_BACKFILL_WINDOW_MINUTES,
                    default=int(
                        options.get(OPT_BACKFILL_WINDOW_MINUTES, DEFAULT_BACKFILL_WINDOW_MINUTES)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_BACKFILL_WINDOW_MINUTES, max=MAX_BACKFILL_WINDOW_MINUTES),
                ),
                vol.Required(
                    OPT_RECENT_CUTOFF_MINUTES,
                    default=int(
                        options.get(OPT_RECENT_CUTOFF_MINUTES, DEFAULT_RECENT_CUTOFF_MINUTES)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_RECENT_CUTOFF_MINUTES, max=MAX_RECENT_CUTOFF_MINUTES),
                ),
                vol.Required(
                    OPT_RSSI_WATCH_THRESHOLD,
                    default=int(
                        options.get(OPT_RSSI_WATCH_THRESHOLD, DEFAULT_RSSI_WATCH_THRESHOLD)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_RSSI_THRESHOLD, max=MAX_RSSI_THRESHOLD),
                ),
                vol.Required(
                    OPT_RSSI_ALERT_THRESHOLD,
                    default=int(
                        options.get(OPT_RSSI_ALERT_THRESHOLD, DEFAULT_RSSI_ALERT_THRESHOLD)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_RSSI_THRESHOLD, max=MAX_RSSI_THRESHOLD),
                ),
                vol.Required(
                    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                    default=int(
                        options.get(
                            OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                            DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
                        )
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_RSSI_ALERT_CONSECUTIVE_POLLS,
                        max=MAX_RSSI_ALERT_CONSECUTIVE_POLLS,
                    ),
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


@dataclass(slots=True)
class ValidationResult:
    """Validation output for credentials."""

    account_id: str
    systems: list[FlowSystemRecord]


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


async def _async_validate_credentials(
    hass: HomeAssistant, username: str, password: str
) -> ValidationResult:
    """Validate credentials and return account/systems."""
    client = TigoApiClient(
        hass=hass,
        credentials=TigoAuthCredentials(username=username, password=password),
    )

    try:
        await client.async_login()
        systems_raw = await client.async_list_systems()
    except TigoApiAuthError as err:
        raise InvalidAuth from err
    except TigoApiConnectionError as err:
        raise CannotConnect from err

    account_id = client.account_id or "unknown"
    systems = [
        FlowSystemRecord(
            system_id=int(item["system_id"]),
            name=str(item.get("name") or f"System {item['system_id']}"),
        )
        for item in systems_raw
        if item.get("system_id") is not None
    ]

    return ValidationResult(account_id=account_id, systems=systems)
