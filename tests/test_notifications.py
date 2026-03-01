"""Tests for integration connectivity notifications."""

from __future__ import annotations

from unittest.mock import patch

from custom_components.tigo_energy.notifications import (
    CONNECTION_SOURCE_MODULES,
    CONNECTION_SOURCE_SUMMARY,
    TigoConnectionNotifier,
)


async def test_connection_notifier_creates_once_for_multiple_sources(hass):
    """First failing source should create one persistent notification."""
    notifier = TigoConnectionNotifier(hass, "entry-1", "Tigo Energy")

    with (
        patch(
            "custom_components.tigo_energy.notifications.persistent_notification.async_create"
        ) as mock_create,
        patch(
            "custom_components.tigo_energy.notifications.persistent_notification.async_dismiss"
        ) as mock_dismiss,
    ):
        await notifier.async_report_connection_failure(CONNECTION_SOURCE_SUMMARY)
        await notifier.async_report_connection_failure(CONNECTION_SOURCE_MODULES)

    assert mock_create.call_count == 1
    mock_dismiss.assert_not_called()


async def test_connection_notifier_dismisses_only_after_all_recover(hass):
    """Notification should clear only when all failing sources recover."""
    notifier = TigoConnectionNotifier(hass, "entry-1", "Tigo Energy")

    with (
        patch(
            "custom_components.tigo_energy.notifications.persistent_notification.async_create"
        ) as mock_create,
        patch(
            "custom_components.tigo_energy.notifications.persistent_notification.async_dismiss"
        ) as mock_dismiss,
    ):
        await notifier.async_report_connection_failure(CONNECTION_SOURCE_SUMMARY)
        await notifier.async_report_connection_failure(CONNECTION_SOURCE_MODULES)

        await notifier.async_report_connection_recovered(CONNECTION_SOURCE_SUMMARY)
        mock_dismiss.assert_not_called()

        await notifier.async_report_connection_recovered(CONNECTION_SOURCE_MODULES)

    assert mock_create.call_count == 1
    mock_dismiss.assert_called_once()
