"""Tests for Tigo sensors."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.const import DOMAIN
from custom_components.tigo_energy.models import (
    FreshnessState,
    SummarySnapshot,
    SystemSnapshot,
    TigoRuntimeData,
)
from custom_components.tigo_energy.sensor import SYSTEM_METRICS, TigoSystemSensor

_LOGGER = logging.getLogger(__name__)


def _metric(key: str):
    return next(description for description in SYSTEM_METRICS if description.key == key)


async def test_telemetry_lag_sensor_exposes_status_attributes(hass):
    """Telemetry lag sensor should expose lag status and related timestamps."""
    source_checkin = datetime(2026, 3, 1, 19, 14, 32, tzinfo=UTC)
    latest_telemetry = datetime(2026, 3, 1, 18, 24, 32, tzinfo=UTC)

    snapshot = SummarySnapshot(
        account_id="42",
        systems={
            1001: SystemSnapshot(
                system_id=1001,
                name="Site One",
                timezone="UTC",
                address=None,
                latitude=None,
                longitude=None,
                turn_on_date="2025-08-24",
                power_rating=5000.0,
                summary={"last_power_dc": 1200},
                sources=[],
                freshest_timestamp=source_checkin,
                latest_source_checkin=source_checkin,
                latest_non_empty_telemetry_timestamp=latest_telemetry,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=3000.0,
                telemetry_lag_status="critical",
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=source_checkin,
            fetched_at=source_checkin,
            lag_seconds=60.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    coordinator.data = snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=coordinator,
        module_coordinator=None,
        tracked_system_ids={1001},
    )

    sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("telemetry_lag_minutes"),
    )

    assert sensor.native_value == 50.0
    attrs = sensor.extra_state_attributes
    assert attrs["telemetry_lag_status"] == "critical"
    assert attrs["lag_warning_minutes"] == 20
    assert attrs["lag_critical_minutes"] == 45
    assert attrs["latest_source_checkin"] == source_checkin
    assert attrs["latest_non_empty_telemetry_timestamp"] == latest_telemetry


async def test_heartbeat_age_sensor_value_is_minutes(hass):
    """Heartbeat age sensor should convert seconds to one-decimal minutes."""
    now = datetime.now(UTC)

    snapshot = SummarySnapshot(
        account_id="42",
        systems={
            1001: SystemSnapshot(
                system_id=1001,
                name="Site One",
                timezone="UTC",
                address=None,
                latitude=None,
                longitude=None,
                turn_on_date="2025-08-24",
                power_rating=5000.0,
                summary={"last_power_dc": 1200},
                sources=[],
                freshest_timestamp=now,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=now,
                heartbeat_age_seconds=615.0,
                telemetry_lag_seconds=120.0,
                telemetry_lag_status="ok",
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=120.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    coordinator.data = snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=coordinator,
        module_coordinator=None,
        tracked_system_ids={1001},
    )

    sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("heartbeat_age_minutes"),
    )

    assert sensor.native_value == 10.2
