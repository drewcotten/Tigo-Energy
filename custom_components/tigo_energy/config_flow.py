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
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    DEFAULT_ENABLE_MODULE_TELEMETRY,
    DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
    DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
    DEFAULT_MODULE_POLL_SECONDS,
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
    MAX_BACKFILL_WINDOW_MINUTES,
    MAX_POLL_SECONDS,
    MAX_RECENT_CUTOFF_MINUTES,
    MAX_RSSI_ALERT_CONSECUTIVE_POLLS,
    MAX_RSSI_THRESHOLD,
    MAX_STALE_THRESHOLD_SECONDS,
    MAX_SUN_GUARD_MIN_ELEVATION_DEGREES,
    MAX_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    MIN_BACKFILL_WINDOW_MINUTES,
    MIN_MODULE_POLL_SECONDS,
    MIN_RECENT_CUTOFF_MINUTES,
    MIN_RSSI_ALERT_CONSECUTIVE_POLLS,
    MIN_RSSI_THRESHOLD,
    MIN_STALE_THRESHOLD_SECONDS,
    MIN_SUMMARY_POLL_SECONDS,
    MIN_SUN_GUARD_MIN_ELEVATION_DEGREES,
    MIN_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
    OPT_ENABLE_SUNSET_ALERT_GUARD,
    OPT_MODULE_POLL_SECONDS,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    SUBENTRY_TYPE_SYSTEM,
)


@dataclass(slots=True)
class FlowSystemRecord:
    """Simple system record for config flow selections."""

    system_id: int
    name: str


def _int_box_selector(min_value: int, max_value: int) -> selector.NumberSelector:
    """Build an integer number selector rendered as a keyboard-editable box."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _float_box_selector(
    min_value: float,
    max_value: float,
    *,
    step: float = 0.1,
) -> selector.NumberSelector:
    """Build a float number selector rendered as a keyboard-editable box."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


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
        self._enable_persistent_notifications: bool = DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS
        self._enable_sunset_alert_guard: bool = DEFAULT_ENABLE_SUNSET_ALERT_GUARD
        self._sun_guard_min_elevation_degrees: float = DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES
        self._sun_guard_positive_power_grace_minutes: int = (
            DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES
        )
        self._enable_alert_feed_notifications: bool = DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS
        self._summary_poll_seconds: int = DEFAULT_SUMMARY_POLL_SECONDS
        self._module_poll_seconds: int = DEFAULT_MODULE_POLL_SECONDS
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
        """Choose module telemetry and initial polling rates."""
        if user_input is not None:
            self._enable_module_telemetry = bool(user_input[OPT_ENABLE_MODULE_TELEMETRY])
            self._enable_persistent_notifications = bool(
                user_input[OPT_ENABLE_PERSISTENT_NOTIFICATIONS]
            )
            self._enable_sunset_alert_guard = bool(user_input[OPT_ENABLE_SUNSET_ALERT_GUARD])
            self._sun_guard_min_elevation_degrees = float(
                user_input[OPT_SUN_GUARD_MIN_ELEVATION_DEGREES]
            )
            self._sun_guard_positive_power_grace_minutes = int(
                user_input[OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES]
            )
            self._enable_alert_feed_notifications = bool(
                user_input[OPT_ENABLE_ALERT_FEED_NOTIFICATIONS]
            )
            self._summary_poll_seconds = int(user_input[OPT_SUMMARY_POLL_SECONDS])
            self._module_poll_seconds = int(user_input[OPT_MODULE_POLL_SECONDS])

            selected_systems = self._selected_system_records()
            if not selected_systems:
                return self.async_abort(reason="no_systems")

            await self.async_set_unique_id(self._account_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Tigo Energy",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_ACCOUNT_ID: self._account_id,
                    CONF_ENTRY_MODE: self._selected_entry_mode,
                },
                subentries=[
                    {
                        "subentry_type": SUBENTRY_TYPE_SYSTEM,
                        "title": record.name,
                        "unique_id": str(record.system_id),
                        "data": {CONF_SYSTEM_ID: record.system_id},
                    }
                    for record in selected_systems
                ],
                options={
                    OPT_SUMMARY_POLL_SECONDS: self._summary_poll_seconds,
                    OPT_MODULE_POLL_SECONDS: self._module_poll_seconds,
                    OPT_ENABLE_MODULE_TELEMETRY: self._enable_module_telemetry,
                    OPT_ENABLE_PERSISTENT_NOTIFICATIONS: self._enable_persistent_notifications,
                    OPT_ENABLE_SUNSET_ALERT_GUARD: self._enable_sunset_alert_guard,
                    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: self._sun_guard_min_elevation_degrees,
                    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: (
                        self._sun_guard_positive_power_grace_minutes
                    ),
                    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS: self._enable_alert_feed_notifications,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_SUMMARY_POLL_SECONDS,
                    default=self._summary_poll_seconds,
                ): _int_box_selector(MIN_SUMMARY_POLL_SECONDS, MAX_POLL_SECONDS),
                vol.Required(
                    OPT_MODULE_POLL_SECONDS,
                    default=self._module_poll_seconds,
                ): _int_box_selector(MIN_MODULE_POLL_SECONDS, MAX_POLL_SECONDS),
                vol.Required(
                    OPT_ENABLE_MODULE_TELEMETRY,
                    default=self._enable_module_telemetry,
                ): bool,
                vol.Required(
                    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
                    default=self._enable_persistent_notifications,
                ): bool,
                vol.Required(
                    OPT_ENABLE_SUNSET_ALERT_GUARD,
                    default=self._enable_sunset_alert_guard,
                ): bool,
                vol.Required(
                    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                    default=self._sun_guard_min_elevation_degrees,
                ): _float_box_selector(
                    MIN_SUN_GUARD_MIN_ELEVATION_DEGREES,
                    MAX_SUN_GUARD_MIN_ELEVATION_DEGREES,
                ),
                vol.Required(
                    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                    default=self._sun_guard_positive_power_grace_minutes,
                ): _int_box_selector(
                    MIN_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                    MAX_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                ),
                vol.Required(
                    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                    default=self._enable_alert_feed_notifications,
                ): bool,
            }
        )
        return self.async_show_form(step_id="module_telemetry", data_schema=schema)

    def _selected_system_records(self) -> list[FlowSystemRecord]:
        """Return systems selected by scope/system selection steps."""
        if self._selected_entry_mode == ENTRY_MODE_ALL_SYSTEMS:
            return list(self._systems)

        if self._selected_system_id is None:
            return []

        selected = [
            record for record in self._systems if record.system_id == self._selected_system_id
        ]
        if selected:
            return selected
        return [FlowSystemRecord(system_id=self._selected_system_id, name=f"System {self._selected_system_id}")]

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

    @classmethod
    @config_entries.callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return supported subentry flow handlers."""
        return {SUBENTRY_TYPE_SYSTEM: TigoSystemSubentryFlow}


class TigoSystemSubentryFlow(config_entries.ConfigSubentryFlow):
    """Handle adding a system subentry to an existing account entry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        """Select and add an additional system."""
        entry = self._get_entry()
        username = str(entry.data.get(CONF_USERNAME, "")).strip()
        password = str(entry.data.get(CONF_PASSWORD, ""))
        if not username or not password:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}

        try:
            validation = await _async_validate_credentials(self.hass, username, password)
        except InvalidAuth:
            errors["base"] = "invalid_auth"
            validation = None
        except CannotConnect:
            errors["base"] = "cannot_connect"
            validation = None
        except Exception:  # pragma: no cover - defensive fallback
            errors["base"] = "unknown"
            validation = None

        existing_system_ids: set[int] = set()
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_SYSTEM:
                continue
            raw_system_id = subentry.data.get(CONF_SYSTEM_ID)
            if raw_system_id is None:
                continue
            try:
                existing_system_ids.add(int(raw_system_id))
            except (TypeError, ValueError):
                continue

        available_systems: list[FlowSystemRecord] = []
        if validation is not None:
            available_systems = [
                record
                for record in validation.systems
                if record.system_id not in existing_system_ids
            ]

        if user_input is not None and validation is not None:
            system_id = int(user_input[CONF_SYSTEM_ID])
            if system_id in existing_system_ids:
                return self.async_abort(reason="already_configured")

            selected = next(
                (record for record in validation.systems if record.system_id == system_id),
                None,
            )
            if selected is None:
                errors["base"] = "no_systems"
            else:
                return self.async_create_entry(
                    title=selected.name,
                    unique_id=str(selected.system_id),
                    data={CONF_SYSTEM_ID: selected.system_id},
                )

        if not errors and not available_systems:
            return self.async_abort(reason="no_unconfigured_systems")

        options = [
            selector.SelectOptionDict(
                value=str(record.system_id),
                label=f"{record.name} ({record.system_id})",
            )
            for record in available_systems
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class TigoOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Tigo Energy."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            clean_input = {
                **user_input,
                OPT_SUMMARY_POLL_SECONDS: int(user_input[OPT_SUMMARY_POLL_SECONDS]),
                OPT_MODULE_POLL_SECONDS: int(user_input[OPT_MODULE_POLL_SECONDS]),
                OPT_STALE_THRESHOLD_SECONDS: int(user_input[OPT_STALE_THRESHOLD_SECONDS]),
                OPT_BACKFILL_WINDOW_MINUTES: int(user_input[OPT_BACKFILL_WINDOW_MINUTES]),
                OPT_RECENT_CUTOFF_MINUTES: int(user_input[OPT_RECENT_CUTOFF_MINUTES]),
                OPT_SUN_GUARD_MIN_ELEVATION_DEGREES: float(
                    user_input[OPT_SUN_GUARD_MIN_ELEVATION_DEGREES]
                ),
                OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES: int(
                    user_input[OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES]
                ),
                OPT_RSSI_WATCH_THRESHOLD: int(user_input[OPT_RSSI_WATCH_THRESHOLD]),
                OPT_RSSI_ALERT_THRESHOLD: int(user_input[OPT_RSSI_ALERT_THRESHOLD]),
                OPT_RSSI_ALERT_CONSECUTIVE_POLLS: int(user_input[OPT_RSSI_ALERT_CONSECUTIVE_POLLS]),
            }

            watch_threshold = clean_input[OPT_RSSI_WATCH_THRESHOLD]
            alert_threshold = clean_input[OPT_RSSI_ALERT_THRESHOLD]
            if watch_threshold <= alert_threshold:
                errors["base"] = "rssi_threshold_order"
            else:
                return self.async_create_entry(title="", data=clean_input)

        options = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_SUMMARY_POLL_SECONDS,
                    default=int(options.get(OPT_SUMMARY_POLL_SECONDS, DEFAULT_SUMMARY_POLL_SECONDS)),
                ): _int_box_selector(MIN_SUMMARY_POLL_SECONDS, MAX_POLL_SECONDS),
                vol.Required(
                    OPT_MODULE_POLL_SECONDS,
                    default=int(options.get(OPT_MODULE_POLL_SECONDS, DEFAULT_MODULE_POLL_SECONDS)),
                ): _int_box_selector(MIN_MODULE_POLL_SECONDS, MAX_POLL_SECONDS),
                vol.Required(
                    OPT_ENABLE_MODULE_TELEMETRY,
                    default=bool(options.get(OPT_ENABLE_MODULE_TELEMETRY, DEFAULT_ENABLE_MODULE_TELEMETRY)),
                ): bool,
                vol.Required(
                    OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
                    default=bool(
                        options.get(
                            OPT_ENABLE_PERSISTENT_NOTIFICATIONS,
                            DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
                        )
                    ),
                ): bool,
                vol.Required(
                    OPT_ENABLE_SUNSET_ALERT_GUARD,
                    default=bool(
                        options.get(
                            OPT_ENABLE_SUNSET_ALERT_GUARD,
                            DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
                        )
                    ),
                ): bool,
                vol.Required(
                    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                    default=float(
                        options.get(
                            OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                            DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                        )
                    ),
                ): _float_box_selector(
                    MIN_SUN_GUARD_MIN_ELEVATION_DEGREES,
                    MAX_SUN_GUARD_MIN_ELEVATION_DEGREES,
                ),
                vol.Required(
                    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                    default=int(
                        options.get(
                            OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                            DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                        )
                    ),
                ): _int_box_selector(
                    MIN_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                    MAX_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                ),
                vol.Required(
                    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                    default=bool(
                        options.get(
                            OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                            DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                        )
                    ),
                ): bool,
                vol.Required(
                    OPT_STALE_THRESHOLD_SECONDS,
                    default=int(
                        options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS)
                    ),
                ): _int_box_selector(MIN_STALE_THRESHOLD_SECONDS, MAX_STALE_THRESHOLD_SECONDS),
                vol.Required(
                    OPT_BACKFILL_WINDOW_MINUTES,
                    default=int(
                        options.get(OPT_BACKFILL_WINDOW_MINUTES, DEFAULT_BACKFILL_WINDOW_MINUTES)
                    ),
                ): _int_box_selector(MIN_BACKFILL_WINDOW_MINUTES, MAX_BACKFILL_WINDOW_MINUTES),
                vol.Required(
                    OPT_RECENT_CUTOFF_MINUTES,
                    default=int(
                        options.get(OPT_RECENT_CUTOFF_MINUTES, DEFAULT_RECENT_CUTOFF_MINUTES)
                    ),
                ): _int_box_selector(MIN_RECENT_CUTOFF_MINUTES, MAX_RECENT_CUTOFF_MINUTES),
                vol.Required(
                    OPT_RSSI_WATCH_THRESHOLD,
                    default=int(
                        options.get(OPT_RSSI_WATCH_THRESHOLD, DEFAULT_RSSI_WATCH_THRESHOLD)
                    ),
                ): _int_box_selector(MIN_RSSI_THRESHOLD, MAX_RSSI_THRESHOLD),
                vol.Required(
                    OPT_RSSI_ALERT_THRESHOLD,
                    default=int(
                        options.get(OPT_RSSI_ALERT_THRESHOLD, DEFAULT_RSSI_ALERT_THRESHOLD)
                    ),
                ): _int_box_selector(MIN_RSSI_THRESHOLD, MAX_RSSI_THRESHOLD),
                vol.Required(
                    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                    default=int(
                        options.get(
                            OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                            DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
                        )
                    ),
                ): _int_box_selector(
                    MIN_RSSI_ALERT_CONSECUTIVE_POLLS,
                    MAX_RSSI_ALERT_CONSECUTIVE_POLLS,
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
