"""Tests for Tigo coordinators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tigo_energy.api import (
    TigoApiConnectionError,
    TigoApiError,
    TigoApiRateLimitError,
)
from custom_components.tigo_energy.const import (
    ENTRY_MODE_SINGLE_SYSTEM,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
)
from custom_components.tigo_energy.coordinator import TigoModuleCoordinator, TigoSummaryCoordinator
from custom_components.tigo_energy.notifications import CONNECTION_SOURCE_SUMMARY


class DummySummary:
    """Simple summary coordinator-like object for module tests."""

    tracked_system_ids: ClassVar[set[int]] = {1001}

    def __init__(self, timezone: str = "UTC") -> None:
        self.data = SimpleNamespace(
            systems={1001: SimpleNamespace(timezone=timezone, module_label_map={})}
        )


def _configure_summary_enrichment_calls(mock_client) -> None:
    """Set defaults for alert/object enrichment endpoints."""
    mock_client.async_get_alert_types.return_value = []
    mock_client.async_get_alerts_system.return_value = ([], {"totalCount": 0})
    mock_client.async_get_objects_system.return_value = []
    mock_client.async_get_system_layout.return_value = {}


async def test_summary_coordinator_fetches_system_and_sources(hass):
    """Summary coordinator returns normalized system data and lag fields."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=8)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {
        "name": "Site One",
        "timezone": "UTC",
        "power_rating": 5000,
    }
    mock_client.async_get_summary.return_value = {
        "last_power_dc": 1200,
        "updated_on": now.isoformat(),
    }
    mock_client.async_get_sources.return_value = [
        {
            "source_id": "src-1",
            "name": "CCA",
            "serial": "ABC123",
            "last_checkin": now.isoformat(),
            "control_state": "PVOn",
            "sw_version": "1.0.0",
        }
    ]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},1100\n"
    )
    _configure_summary_enrichment_calls(mock_client)

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
    system = coordinator.data.systems[1001]
    assert system.summary["last_power_dc"] == 1200
    assert system.latest_non_empty_telemetry_timestamp is not None
    assert system.latest_source_checkin is not None
    assert system.telemetry_lag_status == "ok"
    assert system.system_data_is_stale is False


async def test_summary_coordinator_uses_system_timezone_for_combined_queries(hass):
    """Combined telemetry freshness query should be normalized using system timezone."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=8)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {"name": "Site One", "timezone": "America/Denver"}
    mock_client.async_get_summary.return_value = {
        "last_power_dc": 1200,
        "updated_on": now.isoformat(),
    }
    mock_client.async_get_sources.return_value = [
        {"source_id": "src-1", "name": "CCA", "last_checkin": now.isoformat()}
    ]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},1100\n"
    )
    _configure_summary_enrichment_calls(mock_client)

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )

    await coordinator.async_refresh()

    kwargs = mock_client.async_get_combined_csv.await_args.kwargs
    assert str(kwargs["query_tz"]) == "America/Denver"


async def test_summary_coordinator_critical_lag_notifies_after_debounce(hass):
    """Critical telemetry lag should notify only after configured consecutive polls."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=50)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {
        "name": "Site One",
        "timezone": "UTC",
    }
    mock_client.async_get_summary.return_value = {
        "last_power_dc": 1200,
        "updated_on": now.isoformat(),
    }
    mock_client.async_get_sources.return_value = [
        {
            "source_id": "src-1",
            "name": "CCA",
            "last_checkin": now.isoformat(),
        }
    ]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},1100\n"
    )
    _configure_summary_enrichment_calls(mock_client)

    notifier = AsyncMock()
    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
        connection_notifier=notifier,
    )

    await coordinator.async_refresh()
    assert coordinator.data.systems[1001].telemetry_lag_status == "critical"
    notifier.async_report_telemetry_lag_critical.assert_not_called()

    await coordinator.async_refresh()
    notifier.async_report_telemetry_lag_critical.assert_awaited_once()


async def test_summary_coordinator_alert_state_computation(hass):
    """Alert state should compute active count, latest, and shutdown flags."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=10)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {"name": "Site One", "timezone": "UTC"}
    mock_client.async_get_summary.return_value = {"last_power_dc": 500, "updated_on": now.isoformat()}
    mock_client.async_get_sources.return_value = [
        {"source_id": "src-1", "name": "CCA", "last_checkin": now.isoformat(), "control_state": "on"}
    ]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},300\n"
    )
    mock_client.async_get_alert_types.return_value = [
        {"unique_id": 42, "title": "Tigo Alert: PV-Off Activated — System Shutdown"}
    ]
    mock_client.async_get_alerts_system.return_value = (
        [
            {
                "alert_id": 1,
                "unique_id": 42,
                "title": "Tigo Alert: PV-Off Activated — System Shutdown",
                "message": "String ID 122986273",
                "description": "<p>String shutdown detected.</p>",
                "generated": now.isoformat(),
                "added": now.isoformat(),
                "archived": False,
            },
            {
                "alert_id": 2,
                "unique_id": 999,
                "title": "Archived alert",
                "generated": now.isoformat(),
                "added": now.isoformat(),
                "archived": True,
            },
        ],
        {"totalCount": 2},
    )
    mock_client.async_get_objects_system.return_value = [{"id": 123, "label": "A1"}]
    mock_client.async_get_system_layout.return_value = {}

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )
    await coordinator.async_refresh()

    system = coordinator.data.systems[1001]
    assert system.alert_state.active_count == 1
    assert system.alert_state.latest_active_alert is not None
    assert system.alert_state.latest_active_alert.unique_id == 42
    assert system.alert_state.pv_off_active is True
    assert system.alert_state.string_shutdown_active is True
    assert system.alert_state.alerts_supported is True


async def test_summary_coordinator_alert_fetch_failure_is_soft(hass):
    """Alert endpoint failure should not fail the summary update."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=7)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {"name": "Site One", "timezone": "UTC"}
    mock_client.async_get_summary.return_value = {"last_power_dc": 500, "updated_on": now.isoformat()}
    mock_client.async_get_sources.return_value = [
        {"source_id": "src-1", "name": "CCA", "last_checkin": now.isoformat(), "control_state": "on"}
    ]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},300\n"
    )
    mock_client.async_get_alert_types.return_value = []
    mock_client.async_get_alerts_system.side_effect = TigoApiError("boom")
    mock_client.async_get_objects_system.return_value = []
    mock_client.async_get_system_layout.return_value = {}

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data.systems[1001].alert_state.alerts_supported is False


async def test_summary_coordinator_uses_layout_fallback_for_module_labels(hass):
    """When objects map is empty, layout panels should provide semantic labels."""
    now = datetime.now(UTC)
    telemetry = now - timedelta(minutes=8)

    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.return_value = [{"system_id": 1001, "name": "Site One"}]
    mock_client.async_get_system.return_value = {"name": "Site One", "timezone": "UTC"}
    mock_client.async_get_summary.return_value = {"last_power_dc": 1200, "updated_on": now.isoformat()}
    mock_client.async_get_sources.return_value = [{"source_id": "src-1", "name": "CCA", "last_checkin": now.isoformat()}]
    mock_client.async_get_combined_csv.return_value = (
        "Datetime,combined\n"
        f"{telemetry.strftime('%Y/%m/%d %H:%M:%S')},900\n"
    )
    mock_client.async_get_alert_types.return_value = []
    mock_client.async_get_alerts_system.return_value = ([], {"totalCount": 0})
    mock_client.async_get_objects_system.return_value = []
    mock_client.async_get_system_layout.return_value = {
        "inverters": [
            {
                "label": "Inverter 1",
                "mppts": [
                    {
                        "label": "MPPT 1",
                        "strings": [
                            {
                                "string_id": 57810,
                                "label": "String A",
                                "short_label": "A",
                                "panels": [
                                    {"object_id": 89287797, "panel_id": 650288, "label": "A1"}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )
    await coordinator.async_refresh()

    assert coordinator.data.systems[1001].module_label_map.get("89287797") == "A1"
    arrays = coordinator.data.systems[1001].arrays
    assert "string_57810" in arrays
    assert arrays["string_57810"].name == "Array A"
    assert arrays["string_57810"].panel_labels == ("A1",)
    assert coordinator.data.systems[1001].module_array_map.get("A1") == "string_57810"


async def test_module_coordinator_dedupes_older_points(hass):
    """Module coordinator should keep latest points and dedupe older repeats."""
    now = datetime.now(UTC)
    older = now - timedelta(minutes=2)

    csv_text = (
        "Datetime,mod1\n"
        f"{older.strftime('%Y/%m/%d %H:%M:%S')},100\n"
        f"{now.strftime('%Y/%m/%d %H:%M:%S')},110\n"
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


async def test_module_coordinator_uses_semantic_module_labels(hass):
    """Module keys should map from raw object IDs to semantic labels when available."""
    now = datetime.now(UTC)
    csv_text = (
        "Datetime,89287797\n"
        f"{now.strftime('%Y/%m/%d %H:%M:%S')},111\n"
    )

    mock_client = AsyncMock()
    mock_client.async_get_aggregate_csv.return_value = csv_text

    summary = DummySummary()
    summary.data.systems[1001].module_label_map = {"89287797": "A1"}

    coordinator = TigoModuleCoordinator(
        hass=hass,
        client=mock_client,
        summary_coordinator=summary,
        options={},
    )
    await coordinator.async_refresh()

    assert (1001, "A1", "Pin") in coordinator.data.points_by_key


async def test_module_coordinator_uses_system_timezone_for_aggregate_queries(hass):
    """Module telemetry queries should be normalized using system timezone."""
    now = datetime.now(UTC).astimezone(ZoneInfo("America/Denver"))
    csv_text = (
        "Datetime,mod1\n"
        f"{now.strftime('%Y/%m/%d %H:%M:%S')},100\n"
    )

    mock_client = AsyncMock()
    mock_client.async_get_aggregate_csv.return_value = csv_text

    coordinator = TigoModuleCoordinator(
        hass=hass,
        client=mock_client,
        summary_coordinator=DummySummary(timezone="America/Denver"),
        options={},
    )

    await coordinator.async_refresh()

    assert mock_client.async_get_aggregate_csv.await_count == 4
    for call in mock_client.async_get_aggregate_csv.await_args_list:
        assert str(call.kwargs["query_tz"]) == "America/Denver"


async def test_module_coordinator_uses_empty_window_fallback(hass):
    """Header-only short window should trigger wider fallback and local filtering."""
    now = datetime.now(UTC)

    call_count: dict[str, int] = {}

    def side_effect(*args, **kwargs):
        metric = kwargs["metric"]
        count = call_count.get(metric, 0)
        call_count[metric] = count + 1
        if metric == "Pin" and count == 0:
            return "Datetime,mod1\n"
        return (
            "Datetime,mod1\n"
            f"{(now - timedelta(minutes=30)).strftime('%Y/%m/%d %H:%M:%S')},100\n"
        )

    mock_client = AsyncMock()
    mock_client.async_get_aggregate_csv.side_effect = side_effect

    coordinator = TigoModuleCoordinator(
        hass=hass,
        client=mock_client,
        summary_coordinator=DummySummary(),
        options={},
    )

    await coordinator.async_refresh()

    assert coordinator.data.empty_window_fallback_attempts >= 1
    assert coordinator.data.empty_window_fallback_hits >= 1
    assert coordinator.data.points_by_key[(1001, "mod1", "Pin")].value == 100


async def test_module_coordinator_drops_future_buckets(hass):
    """Rows beyond future skew should be dropped before selecting latest values."""
    now = datetime.now(UTC)
    near = now - timedelta(minutes=5)
    future = now + timedelta(minutes=10)

    csv_text = (
        "Datetime,mod1\n"
        f"{near.strftime('%Y/%m/%d %H:%M:%S')},90\n"
        f"{future.strftime('%Y/%m/%d %H:%M:%S')},999\n"
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

    assert coordinator.data.future_rows_dropped > 0
    assert coordinator.data.points_by_key[(1001, "mod1", "Pin")].value == 90


async def test_summary_coordinator_connection_failure_notifies(hass):
    """Connection failures should trigger user notification path."""
    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.side_effect = TigoApiConnectionError("offline")
    _configure_summary_enrichment_calls(mock_client)

    notifier = AsyncMock()
    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
        connection_notifier=notifier,
    )

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    notifier.async_report_connection_failure.assert_awaited_once_with(CONNECTION_SOURCE_SUMMARY)


async def test_summary_coordinator_rate_limit_sets_retry_after(hass):
    """Rate-limit failures should propagate retry-after to UpdateFailed."""
    mock_client = AsyncMock()
    mock_client.account_id = "42"
    mock_client.async_list_systems.side_effect = TigoApiRateLimitError(
        "rate limited",
        retry_after=12.5,
    )
    _configure_summary_enrichment_calls(mock_client)

    coordinator = TigoSummaryCoordinator(
        hass=hass,
        client=mock_client,
        entry_mode=ENTRY_MODE_SINGLE_SYSTEM,
        configured_system_ids={1001},
        options={},
    )

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.retry_after == 12.5


async def test_module_coordinator_low_rssi_alert_debounced(hass):
    """Low RSSI notification should trigger only after debounce window."""
    now = datetime.now(UTC)
    state = {"rssi": 70.0, "ts": now}

    def side_effect(*args, **kwargs):
        metric = kwargs["metric"]
        value = state["rssi"] if metric == "RSSI" else 100.0
        return f"Datetime,mod1\n{state['ts'].strftime('%Y/%m/%d %H:%M:%S')},{value}\n"

    mock_client = AsyncMock()
    mock_client.async_get_aggregate_csv.side_effect = side_effect

    notifier = AsyncMock()
    coordinator = TigoModuleCoordinator(
        hass=hass,
        client=mock_client,
        summary_coordinator=DummySummary(),
        options={
            OPT_RSSI_WATCH_THRESHOLD: 120,
            OPT_RSSI_ALERT_THRESHOLD: 80,
            OPT_RSSI_ALERT_CONSECUTIVE_POLLS: 2,
        },
        connection_notifier=notifier,
    )

    await coordinator.async_refresh()
    assert coordinator.data.low_rssi_module_count == 1
    notifier.async_report_low_rssi_alert.assert_not_called()

    await coordinator.async_refresh()
    notifier.async_report_low_rssi_alert.assert_awaited_once()

    state["rssi"] = 130.0
    state["ts"] = now + timedelta(minutes=1)
    await coordinator.async_refresh()
    assert coordinator.data.low_rssi_module_count == 0
    notifier.async_clear_low_rssi_alert.assert_awaited_once()
