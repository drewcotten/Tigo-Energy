"""Tests for Tigo coordinators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import AsyncMock

from custom_components.tigo_energy.const import ENTRY_MODE_SINGLE_SYSTEM
from custom_components.tigo_energy.coordinator import TigoModuleCoordinator, TigoSummaryCoordinator


async def test_summary_coordinator_fetches_system_and_sources(hass):
    """Summary coordinator returns normalized system data."""
    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {
        "name": "Site One",
        "timezone": "America/Denver",
        "power_rating": 5000,
    }
    mock_client.async_get_summary.return_value = {
        "last_power_dc": 1200,
        "updated_on": datetime.now(UTC).isoformat(),
    }
    mock_client.async_get_sources.return_value = [
        {
            "source_id": "src-1",
            "name": "CCA",
            "serial": "ABC123",
            "last_checkin": datetime.now(UTC).isoformat(),
            "control_state": "PVOn",
            "sw_version": "1.0.0"
        }
    ]

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert 1001 in coordinator.data.systems
    assert coordinator.data.systems[1001].summary["last_power_dc"] == 1200


async def test_module_coordinator_dedupes_older_points(hass):
    """Module coordinator should keep latest points and dedupe older repeats."""

    class DummySummary:
        tracked_system_ids: ClassVar[set[int]] = {1001}

    now = datetime.now(UTC)
    older = now - timedelta(minutes=2)

    csv_text = (
        "Datetime,mod1\n"
        f"{older.isoformat()},100\n"
        f"{now.isoformat()},110\n"
    )

    mock_client = AsyncMock()
    mock_client.async_get_aggregate_csv.return_value = csv_text

    coordinator = TigoModuleCoordinator(
        hass=hass,
        client=mock_client,
        summary_coordinator=DummySummary(),
        options={},
    )

    await coordinator.async_refresh()
    first_snapshot = coordinator.data
    assert first_snapshot.points_by_key[(1001, "mod1", "Pin")].value == 110

    await coordinator.async_refresh()
    second_snapshot = coordinator.data
    assert second_snapshot.dedupe_ignored_points > 0
    assert second_snapshot.points_by_key[(1001, "mod1", "Pin")].value == 110
