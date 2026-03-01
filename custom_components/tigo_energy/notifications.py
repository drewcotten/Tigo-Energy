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


def low_rssi_notification_id(entry_id: str) -> str:
    """Return stable low-RSSI notification id for one config entry."""
    return f"{DOMAIN}_{entry_id}_low_rssi"


def telemetry_lag_notification_id(entry_id: str) -> str:
    """Return stable telemetry lag notification id for one config entry."""
    return f"{DOMAIN}_{entry_id}_telemetry_lag"


class TigoConnectionNotifier:
    """Tracks connectivity and RSSI alerts via persistent notifications."""

    def __init__(self, hass: HomeAssistant, entry_id: str, entry_title: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._entry_title = entry_title
        self._failed_sources: set[str] = set()

    @property
    def notification_id(self) -> str:
        """Return the persistent notification id."""
        return connection_notification_id(self._entry_id)

    @property
    def low_rssi_alert_notification_id(self) -> str:
        """Return low-RSSI alert notification id."""
        return low_rssi_notification_id(self._entry_id)

    @property
    def telemetry_lag_notification_id(self) -> str:
        """Return telemetry lag notification id."""
        return telemetry_lag_notification_id(self._entry_id)

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
        persistent_notification.async_dismiss(
            self._hass,
            notification_id=self.low_rssi_alert_notification_id,
        )
        persistent_notification.async_dismiss(
            self._hass,
            notification_id=self.telemetry_lag_notification_id,
        )

    async def async_report_low_rssi_alert(
        self,
        *,
        low_count: int,
        watch_count: int,
        worst_rssi: float | None,
        alert_threshold: int,
        watch_threshold: int,
        consecutive_polls: int,
    ) -> None:
        """Create/update persistent alert for sustained low RSSI."""
        worst_text = "unknown" if worst_rssi is None else f"{worst_rssi:.1f}"
        persistent_notification.async_create(
            self._hass,
            message=(
                f"{self._entry_title} has {low_count} module(s) below RSSI {alert_threshold} "
                f"after {consecutive_polls} consecutive poll(s). "
                f"{watch_count} additional module(s) are in watch range "
                f"({alert_threshold}-{watch_threshold - 1}). "
                f"Worst observed RSSI: {worst_text}. "
                "Check gateway placement or add coverage."
            ),
            title=f"{MANUFACTURER}: Low RSSI alert",
            notification_id=self.low_rssi_alert_notification_id,
        )

    async def async_clear_low_rssi_alert(self) -> None:
        """Dismiss low-RSSI alert notification."""
        persistent_notification.async_dismiss(
            self._hass,
            notification_id=self.low_rssi_alert_notification_id,
        )

    async def async_report_telemetry_lag_critical(
        self,
        *,
        critical_system_count: int,
        warning_system_count: int,
        worst_lag_minutes: float | None,
        warning_minutes: int,
        critical_minutes: int,
        consecutive_polls: int,
    ) -> None:
        """Create/update persistent alert for critical telemetry lag."""
        worst_text = "unknown" if worst_lag_minutes is None else f"{worst_lag_minutes:.1f}m"
        persistent_notification.async_create(
            self._hass,
            message=(
                f"{self._entry_title} has {critical_system_count} system(s) with telemetry lag "
                f">= {critical_minutes} minutes for {consecutive_polls} consecutive poll(s). "
                f"{warning_system_count} additional system(s) are in warning range "
                f"({warning_minutes}-{critical_minutes - 1} minutes). "
                f"Worst observed lag: {worst_text}. "
                "This indicates source heartbeat is ahead of available telemetry buckets."
            ),
            title=f"{MANUFACTURER}: Telemetry lag alert",
            notification_id=self.telemetry_lag_notification_id,
        )

    async def async_clear_telemetry_lag_alert(self) -> None:
        """Dismiss telemetry lag alert notification."""
        persistent_notification.async_dismiss(
            self._hass,
            notification_id=self.telemetry_lag_notification_id,
        )
