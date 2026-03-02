"""Tests for Tigo binary sensors."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.binary_sensor import (
    AlertBinaryDescription,
    TigoAlertBinarySensor,
)
from custom_components.tigo_energy.const import DOMAIN
from custom_components.tigo_energy.models import (
    AlertRecord,
    FreshnessState,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
    TigoRuntimeData,
)

_LOGGER = logging.getLogger(__name__)


def _snapshot(pv_off: bool, shutdown: bool) -> SummarySnapshot:
    now = datetime.now(UTC)
    latest = AlertRecord(
        alert_id=1,
        unique_id=42,
        title="PV-Off",
        message="System shutdown",
        description_html="<p>desc</p>",
        added=now,
        generated=now,
        archived=False,
    )
    return SummarySnapshot(
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
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=now,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=120.0,
                telemetry_lag_status="ok",
                alert_state=SystemAlertState(
                    active_count=1,
                    latest_active_alert=latest,
                    pv_off_active=pv_off,
                    string_shutdown_active=shutdown,
                    alerts_supported=True,
                ),
                module_label_map={},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=60.0,
            is_stale=False,
        ),
    )


async def test_pv_off_binary_sensor_state_and_attributes(hass):
    """PV-Off binary sensor should follow computed system alert state."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    coordinator.data = _snapshot(pv_off=True, shutdown=False)

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=coordinator,
        module_coordinator=None,
        tracked_system_ids={1001},
    )

    sensor = TigoAlertBinarySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=AlertBinaryDescription(
            key="pv_off_active",
            translation_key="pv_off_active",
        ),
    )

    assert sensor.is_on is True
    attrs = sensor.extra_state_attributes
    assert attrs["alerts_supported"] is True
    assert attrs["latest_alert_id"] == 1


async def test_shutdown_binary_sensor_off(hass):
    """String shutdown binary sensor should be off when state is false."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-2")
    entry.add_to_hass(hass)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    coordinator.data = _snapshot(pv_off=False, shutdown=False)

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=coordinator,
        module_coordinator=None,
        tracked_system_ids={1001},
    )

    sensor = TigoAlertBinarySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=AlertBinaryDescription(
            key="string_shutdown_active",
            translation_key="string_shutdown_active",
        ),
    )

    assert sensor.is_on is False
