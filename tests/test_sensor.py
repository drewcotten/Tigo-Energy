"""Tests for Tigo sensors."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import Mock

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.const import DOMAIN
from custom_components.tigo_energy.models import (
    AlertRecord,
    FreshnessState,
    ModulePoint,
    ModuleSnapshot,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
    TigoRuntimeData,
)
from custom_components.tigo_energy.sensor import (
    ALERT_METRICS,
    SYSTEM_METRICS,
    TigoEntityManager,
    TigoModuleSensor,
    TigoSystemSensor,
)

_LOGGER = logging.getLogger(__name__)


def _metric(key: str):
    return next(description for description in (*SYSTEM_METRICS, *ALERT_METRICS) if description.key == key)


def _default_alert_state() -> SystemAlertState:
    return SystemAlertState(
        active_count=0,
        latest_active_alert=None,
        pv_off_active=False,
        string_shutdown_active=False,
        alerts_supported=True,
    )


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
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=source_checkin,
                latest_non_empty_telemetry_timestamp=latest_telemetry,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=3000.0,
                telemetry_lag_status="critical",
                alert_state=_default_alert_state(),
                module_label_map={},
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
    assert attrs["system_data_timestamp"] == source_checkin
    assert attrs["system_data_age_seconds"] == 60.0
    assert attrs["system_data_is_stale"] is False


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
                system_data_age_seconds=120.0,
                system_data_is_stale=False,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=now,
                heartbeat_age_seconds=615.0,
                telemetry_lag_seconds=120.0,
                telemetry_lag_status="ok",
                alert_state=_default_alert_state(),
                module_label_map={},
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


async def test_alert_sensors_expose_latest_alert_attributes(hass):
    """Alert sensors should expose latest active alert metadata in attributes."""
    now = datetime.now(UTC)
    latest_alert = AlertRecord(
        alert_id=999,
        unique_id=42,
        title="Tigo Alert: PV-Off Activated",
        message="String shutdown",
        description_html="<p>desc</p>",
        added=now,
        generated=now,
        archived=False,
    )

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
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=now,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=120.0,
                telemetry_lag_status="ok",
                alert_state=SystemAlertState(
                    active_count=1,
                    latest_active_alert=latest_alert,
                    pv_off_active=True,
                    string_shutdown_active=True,
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
        description=_metric("active_alert_count"),
    )

    assert sensor.native_value == 1
    attrs = sensor.extra_state_attributes
    assert attrs["alerts_supported"] is True
    assert attrs["latest_alert_id"] == 999
    assert attrs["latest_alert_unique_id"] == 42
    assert attrs["latest_alert_message"] == "String shutdown"
    assert attrs["latest_alert_description_html"] == "<p>desc</p>"
    assert attrs["latest_alert_archived"] is False


async def test_system_status_and_metadata_sensors(hass):
    """System status/recent alert count/has monitored modules should map correctly."""
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
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=now,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=60.0,
                telemetry_lag_status="ok",
                alert_state=_default_alert_state(),
                system_status="Active",
                recent_alert_count=3,
                has_monitored_modules=True,
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

    status_sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("system_status"),
    )
    recent_alert_sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("recent_alert_count"),
    )
    monitored_sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("has_monitored_modules"),
    )

    assert status_sensor.native_value == "Active"
    assert recent_alert_sensor.native_value == 3
    assert monitored_sensor.native_value is True


async def test_system_sensor_stays_available_when_stale(hass):
    """System sensor remains available; stale is represented via attributes."""
    now = datetime.now(UTC)
    stale_point = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)

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
                freshest_timestamp=stale_point,
                system_data_age_seconds=(now - stale_point).total_seconds(),
                system_data_is_stale=True,
                latest_source_checkin=stale_point,
                latest_non_empty_telemetry_timestamp=stale_point,
                heartbeat_age_seconds=(now - stale_point).total_seconds(),
                telemetry_lag_seconds=0.0,
                telemetry_lag_status="ok",
                alert_state=_default_alert_state(),
                module_label_map={},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=stale_point,
            fetched_at=now,
            lag_seconds=(now - stale_point).total_seconds(),
            is_stale=True,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    summary_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    summary_coordinator.data = snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=summary_coordinator,
        module_coordinator=None,
        tracked_system_ids={1001},
    )

    sensor = TigoSystemSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        description=_metric("last_power_dc"),
    )

    assert sensor.available is True
    attrs = sensor.extra_state_attributes
    assert attrs["is_stale"] is True
    assert attrs["system_data_is_stale"] is True


async def test_module_sensor_available_with_stale_point(hass):
    """Module sensor remains available when point exists, even if stale."""
    now = datetime.now(UTC)
    stale_point = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)

    summary_snapshot = SummarySnapshot(
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
                freshest_timestamp=stale_point,
                system_data_age_seconds=(now - stale_point).total_seconds(),
                system_data_is_stale=True,
                latest_source_checkin=stale_point,
                latest_non_empty_telemetry_timestamp=stale_point,
                heartbeat_age_seconds=(now - stale_point).total_seconds(),
                telemetry_lag_seconds=0.0,
                telemetry_lag_status="ok",
                alert_state=_default_alert_state(),
                module_label_map={},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=stale_point,
            fetched_at=now,
            lag_seconds=(now - stale_point).total_seconds(),
            is_stale=True,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={
            (1001, "mod1", "Pin"): ModulePoint(
                system_id=1001,
                module_id="mod1",
                metric="Pin",
                value=123.0,
                timestamp=stale_point,
            )
        },
        by_system={},
        freshness=FreshnessState(
            latest_stable_timestamp=stale_point,
            fetched_at=now,
            lag_seconds=(now - stale_point).total_seconds(),
            is_stale=True,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    summary_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    summary_coordinator.data = summary_snapshot

    module_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="modules",
        update_method=None,
    )
    module_coordinator.data = module_snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=summary_coordinator,
        module_coordinator=module_coordinator,
        tracked_system_ids={1001},
    )

    sensor = TigoModuleSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        module_id="mod1",
        metric="Pin",
    )

    assert sensor.available is True
    attrs = sensor.extra_state_attributes
    assert attrs["module_data_timestamp"] == stale_point
    assert attrs["module_latest_timestamp"] == stale_point
    assert attrs["module_data_is_stale"] is True
    assert attrs["module_data_age_seconds"] > 0


async def test_module_sensor_uses_system_scoped_panel_naming(hass):
    """Module sensor should present panel naming and deterministic object id."""
    now = datetime.now(UTC)

    summary_snapshot = SummarySnapshot(
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
                telemetry_lag_seconds=60.0,
                telemetry_lag_status="ok",
                alert_state=_default_alert_state(),
                module_label_map={"89287797": "A1"},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=60.0,
            is_stale=False,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={
            (1001, "A1", "Pin"): ModulePoint(
                system_id=1001,
                module_id="A1",
                metric="Pin",
                value=123.0,
                timestamp=now,
            )
        },
        by_system={},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    summary_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    summary_coordinator.data = summary_snapshot

    module_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="modules",
        update_method=None,
    )
    module_coordinator.data = module_snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="single_system",
        summary_coordinator=summary_coordinator,
        module_coordinator=module_coordinator,
        tracked_system_ids={1001},
    )

    sensor = TigoModuleSensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        module_id="A1",
        metric="Pin",
    )

    assert sensor.device_info["name"] == "Site One Panel A1"
    assert sensor._attr_suggested_object_id == "system_1001_panel_a1_pin"


async def test_module_discovery_still_creates_system_entities(hass):
    """System sensors should still be created from module snapshot system ids."""
    now = datetime.now(UTC)

    summary_snapshot = SummarySnapshot(
        account_id="42",
        systems={},
        freshness=FreshnessState(
            latest_stable_timestamp=None,
            fetched_at=now,
            lag_seconds=None,
            is_stale=True,
        ),
    )
    point = ModulePoint(
        system_id=1001,
        module_id="A1",
        metric="Pin",
        value=321.0,
        timestamp=now,
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={(1001, "A1", "Pin"): point},
        by_system={1001: {"A1": {"Pin": point}}},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-1")
    entry.add_to_hass(hass)

    summary_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="summary",
        update_method=None,
    )
    summary_coordinator.data = summary_snapshot

    module_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="modules",
        update_method=None,
    )
    module_coordinator.data = module_snapshot

    runtime = TigoRuntimeData(
        account_id="42",
        entry_mode="all_systems",
        summary_coordinator=summary_coordinator,
        module_coordinator=module_coordinator,
        tracked_system_ids=set(),
    )

    manager = TigoEntityManager(
        entry=entry,
        runtime=runtime,
        async_add_entities=Mock(),
    )
    entities = manager.collect_initial_entities()

    assert any(isinstance(entity, TigoSystemSensor) for entity in entities)
