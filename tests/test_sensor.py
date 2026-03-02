"""Tests for Tigo sensors."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tigo_energy.const import (
    DOMAIN,
    OPT_ENABLE_ARRAY_TELEMETRY,
    OPT_ENABLE_PANEL_TELEMETRY,
)
from custom_components.tigo_energy.models import (
    AlertRecord,
    ArraySnapshot,
    FreshnessState,
    ModulePoint,
    ModuleSnapshot,
    SolarAlertContext,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
    TigoRuntimeData,
)
from custom_components.tigo_energy.sensor import (
    ALERT_METRICS,
    ARRAY_METRICS,
    SOURCE_METRICS,
    SYSTEM_METRICS,
    TigoArraySensor,
    TigoEntityManager,
    TigoModuleSensor,
    TigoRssiAggregateSensor,
    TigoSystemSensor,
)

_LOGGER = logging.getLogger(__name__)


def _metric(key: str):
    return next(description for description in (*SYSTEM_METRICS, *ALERT_METRICS) if description.key == key)


def _array_metric(key: str):
    return next(description for description in ARRAY_METRICS if description.key == key)


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
                latest_positive_telemetry_timestamp=latest_telemetry,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=3000.0,
                telemetry_lag_status="suppressed_night",
                telemetry_lag_status_raw="critical",
                alert_state=_default_alert_state(),
                solar_alert_context=SolarAlertContext(
                    sun_available=True,
                    sun_state="below_horizon",
                    sun_elevation=-7.0,
                    guard_active=False,
                    guard_reason="night_no_recent_production",
                    latest_positive_telemetry_timestamp=latest_telemetry,
                    positive_production_age_minutes=70.0,
                ),
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

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: True,
        },
        entry_id="entry-1",
    )
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
    assert attrs["telemetry_lag_status"] == "suppressed_night"
    assert attrs["telemetry_lag_status_raw"] == "critical"
    assert attrs["lag_warning_minutes"] == 20
    assert attrs["lag_critical_minutes"] == 45
    assert attrs["latest_source_checkin"] == source_checkin
    assert attrs["latest_non_empty_telemetry_timestamp"] == latest_telemetry
    assert attrs["latest_positive_telemetry_timestamp"] == latest_telemetry
    assert attrs["telemetry_lag_guard_active"] is False
    assert attrs["telemetry_lag_guard_reason"] == "night_no_recent_production"
    assert attrs["sun_state"] == "below_horizon"
    assert attrs["sun_elevation"] == -7.0
    assert attrs["positive_production_age_minutes"] == 70.0
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

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: True,
        },
        entry_id="entry-1",
    )
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

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: True,
        },
        entry_id="entry-1",
    )
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


def test_sensor_descriptions_use_ha_sensor_entity_description() -> None:
    """All sensor description sets should use HA SensorEntityDescription."""
    for description in (*SYSTEM_METRICS, *ALERT_METRICS, *SOURCE_METRICS, *ARRAY_METRICS):
        assert type(description).__name__ == "SensorEntityDescription"
        assert hasattr(description, "native_unit_of_measurement")
        assert hasattr(description, "suggested_unit_of_measurement")


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
                arrays={
                    "string_1": ArraySnapshot(
                        array_id="string_1",
                        name="Array A",
                        short_label="A",
                        string_id=1,
                        mppt_label="MPPT 1",
                        inverter_label="Inverter 1",
                        panel_labels=("A1",),
                    )
                },
                module_array_map={"A1": "string_1"},
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
    assert sensor.device_info["via_device"] == (DOMAIN, "array_1001_string_1")
    assert sensor._attr_suggested_object_id == "system_1001_panel_a1_pin"
    attrs = sensor.extra_state_attributes
    assert attrs["module_id"] == "A1"
    assert attrs["raw_module_id"] == "89287797"


async def test_array_sensor_computes_derived_metrics(hass):
    """Array sensors should derive metrics from panel telemetry points."""
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
                module_label_map={},
                arrays={
                    "string_57810": ArraySnapshot(
                        array_id="string_57810",
                        name="Array A",
                        short_label="A",
                        string_id=57810,
                        mppt_label="MPPT 1",
                        inverter_label="Inverter 1",
                        panel_labels=("A1", "A2"),
                    )
                },
                module_array_map={"A1": "string_57810", "A2": "string_57810"},
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
            (1001, "A1", "Pin"): ModulePoint(1001, "A1", "Pin", 120.0, now),
            (1001, "A2", "Pin"): ModulePoint(1001, "A2", "Pin", 130.0, now),
            (1001, "A1", "Vin"): ModulePoint(1001, "A1", "Vin", 39.5, now),
            (1001, "A2", "Vin"): ModulePoint(1001, "A2", "Vin", 40.5, now),
            (1001, "A1", "Iin"): ModulePoint(1001, "A1", "Iin", 6.2, now),
            (1001, "A2", "Iin"): ModulePoint(1001, "A2", "Iin", 6.0, now),
            (1001, "A1", "RSSI"): ModulePoint(1001, "A1", "RSSI", 78.0, now),
            (1001, "A2", "RSSI"): ModulePoint(1001, "A2", "RSSI", 121.0, now),
        },
        by_system={
            1001: {
                "A1": {
                    "Pin": ModulePoint(1001, "A1", "Pin", 120.0, now),
                    "Vin": ModulePoint(1001, "A1", "Vin", 39.5, now),
                    "Iin": ModulePoint(1001, "A1", "Iin", 6.2, now),
                    "RSSI": ModulePoint(1001, "A1", "RSSI", 78.0, now),
                },
                "A2": {
                    "Pin": ModulePoint(1001, "A2", "Pin", 130.0, now),
                    "Vin": ModulePoint(1001, "A2", "Vin", 40.5, now),
                    "Iin": ModulePoint(1001, "A2", "Iin", 6.0, now),
                    "RSSI": ModulePoint(1001, "A2", "RSSI", 121.0, now),
                },
            }
        },
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-array")
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

    power_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_power"),
    )
    voltage_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_voltage"),
    )
    voltage_average_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_voltage_average"),
    )
    coverage_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_reporting_coverage"),
    )
    worst_rssi_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_rssi_worst"),
    )
    low_rssi_count_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_rssi_low_count"),
    )
    latest_stable_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_latest_stable_panel_data_timestamp"),
    )
    lag_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_57810",
        description=_array_metric("array_telemetry_lag_minutes"),
    )

    assert power_sensor.native_value == 250.0
    assert voltage_sensor.native_value == 80.0
    assert voltage_average_sensor.native_value == 40.0
    assert coverage_sensor.native_value == 100.0
    assert worst_rssi_sensor.native_value == 78.0
    assert low_rssi_count_sensor.native_value == 1
    assert latest_stable_sensor.native_value == now
    assert lag_sensor.native_value == 0.0
    assert power_sensor.device_info["name"] == "Site One Array A"
    attrs = coverage_sensor.extra_state_attributes
    assert attrs["array_module_count"] == 2
    assert attrs["array_reporting_module_count"] == 2
    lag_attrs = lag_sensor.extra_state_attributes
    assert lag_attrs["array_telemetry_lag_status"] == "ok"
    assert lag_attrs["array_lag_warning_minutes"] == 20
    assert lag_attrs["array_lag_critical_minutes"] == 45
    assert lag_attrs["array_latest_source_checkin"] == now
    assert lag_attrs["array_latest_non_empty_panel_timestamp"] == now
    assert lag_attrs["array_lag_basis"] == "Pin"
    assert lag_attrs["array_panel_data_age_seconds"] == 0.0
    assert lag_attrs["array_panel_data_is_stale"] is False


async def test_array_lag_sensor_handles_missing_pin_or_source(hass):
    """Array lag/timestamp should be unknown without Pin point or source check-in."""
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
                latest_source_checkin=None,
                latest_non_empty_telemetry_timestamp=None,
                heartbeat_age_seconds=None,
                telemetry_lag_seconds=None,
                telemetry_lag_status="unknown",
                alert_state=_default_alert_state(),
                module_label_map={},
                arrays={
                    "string_1": ArraySnapshot(
                        array_id="string_1",
                        name="Array A",
                        short_label="A",
                        string_id=1,
                        mppt_label="MPPT 1",
                        inverter_label="Inverter 1",
                        panel_labels=("A1",),
                    )
                },
                module_array_map={"A1": "string_1"},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={(1001, "A1", "Vin"): ModulePoint(1001, "A1", "Vin", 39.5, now)},
        by_system={1001: {"A1": {"Vin": ModulePoint(1001, "A1", "Vin", 39.5, now)}}},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-array-missing")
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
    lag_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_1",
        description=_array_metric("array_telemetry_lag_minutes"),
    )
    timestamp_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_1",
        description=_array_metric("array_latest_stable_panel_data_timestamp"),
    )

    assert timestamp_sensor.native_value is None
    assert lag_sensor.native_value is None
    attrs = lag_sensor.extra_state_attributes
    assert attrs["array_telemetry_lag_status"] == "unknown"
    assert attrs["array_latest_source_checkin"] is None
    assert attrs["array_latest_non_empty_panel_timestamp"] is None
    assert attrs["array_panel_data_age_seconds"] is None
    assert attrs["array_panel_data_is_stale"] is True


async def test_array_lag_sensor_marks_stale_and_critical_for_old_pin(hass):
    """Array lag attributes should reflect old Pin timestamp age and lag status."""
    fetched_at = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)
    old_pin = fetched_at - timedelta(minutes=50)
    source_checkin = fetched_at

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
                freshest_timestamp=source_checkin,
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=source_checkin,
                latest_non_empty_telemetry_timestamp=old_pin,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=3000.0,
                telemetry_lag_status="critical",
                alert_state=_default_alert_state(),
                module_label_map={},
                arrays={
                    "string_1": ArraySnapshot(
                        array_id="string_1",
                        name="Array A",
                        short_label="A",
                        string_id=1,
                        mppt_label="MPPT 1",
                        inverter_label="Inverter 1",
                        panel_labels=("A1",),
                    )
                },
                module_array_map={"A1": "string_1"},
            )
        },
        freshness=FreshnessState(
            latest_stable_timestamp=source_checkin,
            fetched_at=fetched_at,
            lag_seconds=60.0,
            is_stale=False,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={(1001, "A1", "Pin"): ModulePoint(1001, "A1", "Pin", 120.0, old_pin)},
        by_system={1001: {"A1": {"Pin": ModulePoint(1001, "A1", "Pin", 120.0, old_pin)}}},
        freshness=FreshnessState(
            latest_stable_timestamp=old_pin,
            fetched_at=fetched_at,
            lag_seconds=3000.0,
            is_stale=True,
        ),
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Tigo", data={}, entry_id="entry-array-old")
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
    lag_sensor = TigoArraySensor(
        entry=entry,
        runtime=runtime,
        system_id=1001,
        array_id="string_1",
        description=_array_metric("array_telemetry_lag_minutes"),
    )

    assert lag_sensor.native_value == 50.0
    attrs = lag_sensor.extra_state_attributes
    assert attrs["array_telemetry_lag_status"] == "critical"
    assert attrs["array_panel_data_age_seconds"] == 3000.0
    assert attrs["array_panel_data_is_stale"] is True


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


async def test_module_entities_created_from_summary_inventory_without_points(hass):
    """Panel entities should be created from summary topology even with no telemetry points."""
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
                summary={"last_power_dc": 0},
                sources=[],
                freshest_timestamp=now,
                system_data_age_seconds=60.0,
                system_data_is_stale=False,
                latest_source_checkin=now,
                latest_non_empty_telemetry_timestamp=None,
                heartbeat_age_seconds=60.0,
                telemetry_lag_seconds=None,
                telemetry_lag_status="unknown",
                alert_state=_default_alert_state(),
                module_label_map={"89287797": "A1", "89287798": "A2"},
                arrays={
                    "string_1": ArraySnapshot(
                        array_id="string_1",
                        name="Array A",
                        short_label="A",
                        string_id=1,
                        mppt_label="MPPT 1",
                        inverter_label="Inverter 1",
                        panel_labels=("A1", "A2"),
                    )
                },
                module_array_map={"A1": "string_1", "A2": "string_1"},
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
        points_by_key={},
        by_system={},
        freshness=FreshnessState(
            latest_stable_timestamp=None,
            fetched_at=now,
            lag_seconds=None,
            is_stale=True,
        ),
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: True,
        },
        entry_id="entry-1",
    )
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

    manager = TigoEntityManager(
        entry=entry,
        runtime=runtime,
        async_add_entities=Mock(),
    )
    entities = manager.collect_initial_entities()
    module_entities = [entity for entity in entities if isinstance(entity, TigoModuleSensor)]

    assert len(module_entities) == 8
    pin_a1 = next(
        entity for entity in module_entities if entity._module_id == "A1" and entity._metric == "Pin"
    )
    assert pin_a1.available is True
    assert pin_a1.native_value is None


async def test_entity_manager_array_on_panel_off_creates_array_not_panel(hass):
    """Array-enabled/panel-disabled should create array + RSSI aggregate entities only."""
    now = datetime.now(UTC)
    system_snapshot = SystemSnapshot(
        system_id=1001,
        name="Site One",
        timezone="UTC",
        address=None,
        latitude=None,
        longitude=None,
        turn_on_date="2025-08-24",
        power_rating=5000.0,
        summary={"last_power_dc": 0},
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
        arrays={
            "string_1": ArraySnapshot(
                array_id="string_1",
                name="Array A",
                short_label="A",
                string_id=1,
                mppt_label="MPPT 1",
                inverter_label="Inverter 1",
                panel_labels=("A1",),
            )
        },
        module_array_map={"A1": "string_1"},
    )
    summary_snapshot = SummarySnapshot(
        account_id="42",
        systems={1001: system_snapshot},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={(1001, "A1", "Pin"): ModulePoint(1001, "A1", "Pin", 120.0, now)},
        by_system={1001: {"A1": {"Pin": ModulePoint(1001, "A1", "Pin", 120.0, now)}}},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: True,
            OPT_ENABLE_PANEL_TELEMETRY: False,
        },
        entry_id="entry-array-only",
    )
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
    manager = TigoEntityManager(entry=entry, runtime=runtime, async_add_entities=Mock())
    entities = manager.collect_initial_entities()

    assert any(isinstance(entity, TigoArraySensor) for entity in entities)
    assert any(isinstance(entity, TigoRssiAggregateSensor) for entity in entities)
    assert not any(isinstance(entity, TigoModuleSensor) for entity in entities)


async def test_entity_manager_array_off_panel_on_creates_panel_not_array(hass):
    """Array-disabled/panel-enabled should create panel entities only."""
    now = datetime.now(UTC)
    system_snapshot = SystemSnapshot(
        system_id=1001,
        name="Site One",
        timezone="UTC",
        address=None,
        latitude=None,
        longitude=None,
        turn_on_date="2025-08-24",
        power_rating=5000.0,
        summary={"last_power_dc": 0},
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
        arrays={
            "string_1": ArraySnapshot(
                array_id="string_1",
                name="Array A",
                short_label="A",
                string_id=1,
                mppt_label="MPPT 1",
                inverter_label="Inverter 1",
                panel_labels=("A1",),
            )
        },
        module_array_map={"A1": "string_1"},
    )
    summary_snapshot = SummarySnapshot(
        account_id="42",
        systems={1001: system_snapshot},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )
    module_snapshot = ModuleSnapshot(
        points_by_key={(1001, "A1", "Pin"): ModulePoint(1001, "A1", "Pin", 120.0, now)},
        by_system={1001: {"A1": {"Pin": ModulePoint(1001, "A1", "Pin", 120.0, now)}}},
        freshness=FreshnessState(
            latest_stable_timestamp=now,
            fetched_at=now,
            lag_seconds=0.0,
            is_stale=False,
        ),
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tigo",
        data={},
        options={
            OPT_ENABLE_ARRAY_TELEMETRY: False,
            OPT_ENABLE_PANEL_TELEMETRY: True,
        },
        entry_id="entry-panel-only",
    )
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
    manager = TigoEntityManager(entry=entry, runtime=runtime, async_add_entities=Mock())
    entities = manager.collect_initial_entities()

    assert any(isinstance(entity, TigoModuleSensor) for entity in entities)
    assert not any(isinstance(entity, TigoArraySensor) for entity in entities)
    assert not any(isinstance(entity, TigoRssiAggregateSensor) for entity in entities)
