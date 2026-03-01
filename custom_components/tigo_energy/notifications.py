"""User-facing notifications for the Tigo Energy integration."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MANUFACTURER

CONNECTION_SOURCE_SETUP = "setup"
CONNECTION_SOURCE_SUMMARY = "summary"
CONNECTION_SOURCE_MODULES = "modules"


def connection_notification_id(entry_id: str) -> str:
    """Return stable notification id for one config entry."""
    return f"{DOMAIN}_{entry_id}_cannot_connect"


class TigoConnectionNotifier:
    """Tracks connectivity failures and manages one persistent notification."""

    def __init__(self, hass: HomeAssistant, entry_id: str, entry_title: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._entry_title = entry_title
        self._failed_sources: set[str] = set()

    @property
    def notification_id(self) -> str:
        """Return the persistent notification id."""
        return connection_notification_id(self._entry_id)

    async def async_report_connection_failure(self, source: str) -> None:
        """Mark one source as failed and create notification when first failing."""
        had_failures = bool(self._failed_sources)
        self._failed_sources.add(source)
        if had_failures:
            return

        persistent_notification.async_create(
            self._hass,
            message=(
                f"{self._entry_title} cannot currently reach the Tigo cloud API. "
                "The integration will retry automatically."
            ),
            title=f"{MANUFACTURER}: Connection issue",
            notification_id=self.notification_id,
        )

    async def async_report_connection_recovered(self, source: str) -> None:
        """Mark one source recovered and dismiss when all sources recover."""
        had_source = source in self._failed_sources
        self._failed_sources.discard(source)
        if had_source and not self._failed_sources:
            persistent_notification.async_dismiss(
                self._hass,
                notification_id=self.notification_id,
            )

    async def async_clear(self) -> None:
        """Clear any tracked failures and dismiss notification."""
        self._failed_sources.clear()
        persistent_notification.async_dismiss(
            self._hass,
            notification_id=self.notification_id,
        )
