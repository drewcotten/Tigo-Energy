"""Sensor platform for the Tigo Energy integration."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ALERTS_SUPPORTED,
    ATTR_ARRAY_LAG_BASIS,
    ATTR_ARRAY_LAG_CRITICAL_MINUTES,
    ATTR_ARRAY_LAG_WARNING_MINUTES,
    ATTR_ARRAY_LATEST_NON_EMPTY_PANEL_TIMESTAMP,
    ATTR_ARRAY_LATEST_SOURCE_CHECKIN,
    ATTR_ARRAY_PANEL_DATA_AGE_SECONDS,
    ATTR_ARRAY_PANEL_DATA_IS_STALE,
    ATTR_ARRAY_TELEMETRY_LAG_STATUS,
    ATTR_DATA_LAG_SECONDS,
    ATTR_IS_STALE,
    ATTR_LAG_CRITICAL_MINUTES,
    ATTR_LAG_WARNING_MINUTES,
    ATTR_LATEST_ALERT_ARCHIVED,
    ATTR_LATEST_ALERT_DESCRIPTION_HTML,
    ATTR_LATEST_ALERT_ID,
    ATTR_LATEST_ALERT_MESSAGE,
    ATTR_LATEST_ALERT_UNIQUE_ID,
    ATTR_LATEST_NON_EMPTY_TELEMETRY_TIMESTAMP,
    ATTR_LATEST_POSITIVE_TELEMETRY_TIMESTAMP,
    ATTR_LATEST_SOURCE_CHECKIN,
    ATTR_LATEST_STABLE_TIMESTAMP,
    ATTR_MODULE_DATA_AGE_SECONDS,
    ATTR_MODULE_DATA_IS_STALE,
    ATTR_MODULE_DATA_TIMESTAMP,
    ATTR_POSITIVE_PRODUCTION_AGE_MINUTES,
    ATTR_SUN_ELEVATION,
    ATTR_SUN_STATE,
    ATTR_SYSTEM_DATA_AGE_SECONDS,
    ATTR_SYSTEM_DATA_IS_STALE,
    ATTR_SYSTEM_DATA_TIMESTAMP,
    ATTR_TELEMETRY_LAG_GUARD_ACTIVE,
    ATTR_TELEMETRY_LAG_GUARD_REASON,
    ATTR_TELEMETRY_LAG_STATUS,
    ATTR_TELEMETRY_LAG_STATUS_RAW,
    DEFAULT_ENABLE_ARRAY_TELEMETRY,
    DEFAULT_ENABLE_PANEL_TELEMETRY,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DOMAIN,
    LAG_CRITICAL_MINUTES,
    LAG_WARNING_MINUTES,
    MANUFACTURER,
    OPT_ENABLE_ARRAY_TELEMETRY,
    OPT_ENABLE_MODULE_TELEMETRY,
    OPT_ENABLE_PANEL_TELEMETRY,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
)
from .coordinator import METRICS
from .models import (
    ArraySnapshot,
    ModulePoint,
    ModuleSnapshot,
    SourceSnapshot,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
    TigoRuntimeData,
)

OBJECT_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")
PANEL_LABEL_PATTERN = re.compile(r"^[A-Za-z]+[0-9]+$")

SYSTEM_METRICS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="last_power_dc",
        translation_key="current_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="daily_energy_dc",
        translation_key="daily_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="ytd_energy_dc",
        translation_key="ytd_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="lifetime_energy_dc",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="freshness_timestamp",
        translation_key="latest_stable_data_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="telemetry_lag_minutes",
        translation_key="telemetry_lag_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="heartbeat_age_minutes",
        translation_key="heartbeat_age_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

ALERT_METRICS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="system_status",
        translation_key="system_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="recent_alert_count",
        translation_key="recent_alert_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="has_monitored_modules",
        translation_key="has_monitored_modules",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="active_alert_count",
        translation_key="active_alert_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="latest_alert_title",
        translation_key="latest_alert_title",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="latest_alert_code",
        translation_key="latest_alert_code",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="latest_alert_time",
        translation_key="latest_alert_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

RSSI_AGGREGATE_METRICS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="low_rssi_module_count",
        translation_key="low_rssi_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="watch_rssi_module_count",
        translation_key="watch_rssi_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="worst_rssi",
        translation_key="worst_module_rssi",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

SOURCE_METRICS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="last_checkin",
        translation_key="source_last_checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="control_state",
        translation_key="source_control_state",
    ),
    SensorEntityDescription(
        key="sw_version",
        translation_key="source_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="gateway_count",
        translation_key="source_gateway_count",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="serial",
        translation_key="source_serial",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

ARRAY_METRICS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="array_power",
        translation_key="array_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="array_voltage",
        translation_key="array_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="array_voltage_average",
        translation_key="array_voltage_average",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_voltage_min",
        translation_key="array_voltage_min",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_voltage_max",
        translation_key="array_voltage_max",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_current_average",
        translation_key="array_current_average",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="array_current_min",
        translation_key="array_current_min",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_current_max",
        translation_key="array_current_max",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_rssi_average",
        translation_key="array_rssi_average",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_rssi_worst",
        translation_key="array_rssi_worst",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_rssi_low_count",
        translation_key="array_rssi_low_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_rssi_watch_count",
        translation_key="array_rssi_watch_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_module_count",
        translation_key="array_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_reporting_module_count",
        translation_key="array_reporting_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_reporting_coverage",
        translation_key="array_reporting_coverage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_latest_stable_panel_data_timestamp",
        translation_key="array_latest_stable_panel_data_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="array_telemetry_lag_minutes",
        translation_key="array_telemetry_lag_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

MODULE_METRIC_UNITS: dict[str, str | None] = {
    "Pin": UnitOfPower.WATT,
    "Vin": UnitOfElectricPotential.VOLT,
    "Iin": UnitOfElectricCurrent.AMPERE,
    "RSSI": None,
}

MODULE_METRIC_DEVICE_CLASSES: dict[str, SensorDeviceClass | None] = {
    "Pin": SensorDeviceClass.POWER,
    "Vin": SensorDeviceClass.VOLTAGE,
    "Iin": SensorDeviceClass.CURRENT,
    "RSSI": None,
}


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    runtime: TigoRuntimeData = entry.runtime_data

    def _async_add_grouped(entities: list[SensorEntity]) -> None:
        groups: dict[str | None, list[SensorEntity]] = {}
        for entity in entities:
            system_id = getattr(entity, "_system_id", None)
            subentry_id = (
                runtime.system_subentry_ids.get(system_id)
                if isinstance(system_id, int)
                else None
            )
            groups.setdefault(subentry_id, []).append(entity)

        for subentry_id, grouped_entities in groups.items():
            async_add_entities(grouped_entities, config_subentry_id=subentry_id)

    entity_manager = TigoEntityManager(entry, runtime, _async_add_grouped)

    initial_entities = entity_manager.collect_initial_entities()
    if initial_entities:
        _async_add_grouped(initial_entities)

    entry.async_on_unload(
        runtime.summary_coordinator.async_add_listener(entity_manager.handle_summary_update)
    )

    if runtime.module_coordinator is not None:
        entry.async_on_unload(
            runtime.module_coordinator.async_add_listener(entity_manager.handle_module_update)
        )


class TigoEntityManager:
    """Track known entity keys and add new entities for dynamic systems/modules."""

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        async_add_entities: Callable[[list[SensorEntity]], None],
    ) -> None:
        self._entry = entry
        self._runtime = runtime
        self._async_add_entities = async_add_entities

        self._known_system_metric_keys: set[tuple[int, str]] = set()
        self._known_source_metric_keys: set[tuple[int, str, str]] = set()
        self._known_module_metric_keys: set[tuple[int, str, str]] = set()
        self._known_rssi_aggregate_keys: set[tuple[int, str]] = set()
        self._known_array_metric_keys: set[tuple[int, str, str]] = set()

    def collect_initial_entities(self) -> list[SensorEntity]:
        """Collect initial entities from current coordinator data."""
        entities: list[SensorEntity] = []
        summary_data = self._runtime.summary_coordinator.data
        module_data = self._runtime.module_coordinator.data if self._runtime.module_coordinator else None
        system_ids = self._candidate_system_ids(summary_data, module_data)

        entities.extend(self._new_system_entities(system_ids))
        entities.extend(self._new_source_entities(summary_data))

        if module_data is not None and self._array_telemetry_enabled():
            entities.extend(self._new_array_entities(summary_data))
            entities.extend(self._new_rssi_aggregate_entities(system_ids))
        if module_data is not None and self._panel_telemetry_enabled():
            entities.extend(self._new_module_entities(summary_data, module_data))

        return entities

    def handle_summary_update(self) -> None:
        """Add entities for newly discovered systems/sources."""
        new_entities: list[SensorEntity] = []
        data = self._runtime.summary_coordinator.data
        self._runtime.tracked_system_ids = set(data.systems) | self._module_system_ids()
        module_data = self._runtime.module_coordinator.data if self._runtime.module_coordinator else None
        system_ids = self._candidate_system_ids(data, module_data)

        new_entities.extend(self._new_system_entities(system_ids))
        new_entities.extend(self._new_source_entities(data))
        if self._runtime.module_coordinator is not None:
            new_entities.extend(self._new_array_entities(data))
            new_entities.extend(self._new_rssi_aggregate_entities(system_ids))
            module_data = self._runtime.module_coordinator.data
            new_entities.extend(self._new_module_entities(data, module_data))
        if new_entities:
            self._async_add_entities(new_entities)

    def handle_module_update(self) -> None:
        """Add entities for newly discovered modules."""
        if self._runtime.module_coordinator is None:
            return

        module_data = self._runtime.module_coordinator.data
        system_ids = self._candidate_system_ids(self._runtime.summary_coordinator.data, module_data)
        new_entities = self._new_system_entities(system_ids)
        new_entities.extend(self._new_array_entities(self._runtime.summary_coordinator.data))
        new_entities.extend(self._new_module_entities(self._runtime.summary_coordinator.data, module_data))
        new_entities.extend(self._new_rssi_aggregate_entities(system_ids))
        if new_entities:
            self._async_add_entities(new_entities)

    def _new_system_entities(self, system_ids: set[int]) -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []
        for system_id in sorted(system_ids):
            for description in (*SYSTEM_METRICS, *ALERT_METRICS):
                key = (system_id, description.key)
                if key in self._known_system_metric_keys:
                    continue
                self._known_system_metric_keys.add(key)
                new_entities.append(
                    TigoSystemSensor(
                        entry=self._entry,
                        runtime=self._runtime,
                        system_id=system_id,
                        description=description,
                    )
                )
        return new_entities

    def _new_source_entities(self, data: SummarySnapshot) -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []
        for system in data.systems.values():
            for source in system.sources:
                for description in SOURCE_METRICS:
                    key = (system.system_id, source.source_id, description.key)
                    if key in self._known_source_metric_keys:
                        continue
                    self._known_source_metric_keys.add(key)
                    new_entities.append(
                        TigoSourceSensor(
                            entry=self._entry,
                            runtime=self._runtime,
                            system_id=system.system_id,
                            source_id=source.source_id,
                            source_name=source.name,
                            description=description,
                        )
                    )
        return new_entities

    def _new_module_entities(
        self,
        summary_data: SummarySnapshot,
        module_data: ModuleSnapshot | None,
    ) -> list[SensorEntity]:
        if not self._panel_telemetry_enabled():
            return []

        new_entities: list[SensorEntity] = []
        known_modules_by_system: dict[int, set[str]] = {}

        # Primary source: topology/inventory labels from summary layout/full/object mapping.
        for system_id, system in summary_data.systems.items():
            inventory_labels = set(_system_panel_labels(system))
            if inventory_labels:
                known_modules_by_system.setdefault(system_id, set()).update(inventory_labels)

        # Fallback source: any module IDs already seen in telemetry snapshots.
        if module_data is not None:
            for system_id, modules in module_data.by_system.items():
                known_modules_by_system.setdefault(system_id, set()).update(modules)

        for system_id, module_ids in known_modules_by_system.items():
            for module_id in sorted(module_ids, key=_panel_sort_key):
                for metric in METRICS:
                    key = (system_id, module_id, metric)
                    if key in self._known_module_metric_keys:
                        continue
                    self._known_module_metric_keys.add(key)
                    new_entities.append(
                        TigoModuleSensor(
                            entry=self._entry,
                            runtime=self._runtime,
                            system_id=system_id,
                            module_id=module_id,
                            metric=metric,
                        )
                    )
        return new_entities

    def _new_array_entities(self, data: SummarySnapshot) -> list[SensorEntity]:
        """Create per-array aggregate entities for systems."""
        if not self._array_telemetry_enabled():
            return []
        if self._runtime.module_coordinator is None:
            return []

        new_entities: list[SensorEntity] = []
        for system in data.systems.values():
            for array_id in sorted(system.arrays):
                for description in ARRAY_METRICS:
                    key = (system.system_id, array_id, description.key)
                    if key in self._known_array_metric_keys:
                        continue
                    self._known_array_metric_keys.add(key)
                    new_entities.append(
                        TigoArraySensor(
                            entry=self._entry,
                            runtime=self._runtime,
                            system_id=system.system_id,
                            array_id=array_id,
                            description=description,
                        )
                    )
        return new_entities

    def _new_rssi_aggregate_entities(self, system_ids: set[int]) -> list[SensorEntity]:
        """Create RSSI aggregate entities for systems."""
        if not self._array_telemetry_enabled():
            return []
        if self._runtime.module_coordinator is None:
            return []

        new_entities: list[SensorEntity] = []
        for system_id in sorted(system_ids):
            for description in RSSI_AGGREGATE_METRICS:
                key = (system_id, description.key)
                if key in self._known_rssi_aggregate_keys:
                    continue
                self._known_rssi_aggregate_keys.add(key)
                new_entities.append(
                    TigoRssiAggregateSensor(
                        entry=self._entry,
                        runtime=self._runtime,
                        system_id=system_id,
                        description=description,
                    )
                )
        return new_entities

    def _candidate_system_ids(
        self,
        summary_data: SummarySnapshot | None,
        module_data: ModuleSnapshot | None,
    ) -> set[int]:
        """Return all known system IDs from runtime, summary, and module snapshots."""
        system_ids = set(self._runtime.tracked_system_ids)
        if summary_data is not None:
            system_ids.update(summary_data.systems)
        if module_data is not None:
            system_ids.update(module_data.by_system)
        return system_ids

    def _module_system_ids(self) -> set[int]:
        """Return currently known module system IDs, if module polling is enabled."""
        if self._runtime.module_coordinator is None:
            return set()
        return set(self._runtime.module_coordinator.data.by_system)

    def _array_telemetry_enabled(self) -> bool:
        """Return whether per-array telemetry entities are enabled."""
        return bool(
            self._entry.options.get(
                OPT_ENABLE_ARRAY_TELEMETRY,
                DEFAULT_ENABLE_ARRAY_TELEMETRY,
            )
        )

    def _panel_telemetry_enabled(self) -> bool:
        """Return whether per-panel telemetry entities are enabled."""
        legacy_panel_enabled = bool(
            self._entry.options.get(
                OPT_ENABLE_MODULE_TELEMETRY,
                DEFAULT_ENABLE_PANEL_TELEMETRY,
            )
        )
        return bool(
            self._entry.options.get(
                OPT_ENABLE_PANEL_TELEMETRY,
                legacy_panel_enabled,
            )
        )


class TigoBaseEntity(CoordinatorEntity, SensorEntity):
    """Base entity for Tigo coordinator-backed sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        coordinator,
        system_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._runtime = runtime
        self._system_id = system_id

    @property
    def available(self) -> bool:
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        freshness = self._runtime.summary_coordinator.data.freshness
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        solar = system.solar_alert_context if system else None
        return {
            ATTR_LATEST_STABLE_TIMESTAMP: freshness.latest_stable_timestamp,
            ATTR_IS_STALE: freshness.is_stale,
            ATTR_DATA_LAG_SECONDS: freshness.lag_seconds,
            ATTR_SYSTEM_DATA_TIMESTAMP: system.freshest_timestamp if system else None,
            ATTR_SYSTEM_DATA_AGE_SECONDS: system.system_data_age_seconds if system else None,
            ATTR_SYSTEM_DATA_IS_STALE: system.system_data_is_stale if system else True,
            ATTR_LATEST_POSITIVE_TELEMETRY_TIMESTAMP: (
                system.latest_positive_telemetry_timestamp if system else None
            ),
            ATTR_POSITIVE_PRODUCTION_AGE_MINUTES: (
                solar.positive_production_age_minutes if solar else None
            ),
            ATTR_SUN_STATE: solar.sun_state if solar else None,
            ATTR_SUN_ELEVATION: solar.sun_elevation if solar else None,
            ATTR_TELEMETRY_LAG_GUARD_ACTIVE: solar.guard_active if solar else None,
            ATTR_TELEMETRY_LAG_GUARD_REASON: solar.guard_reason if solar else None,
        }

    @property
    def device_info(self) -> DeviceInfo:
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        name = system.name if system else f"System {self._system_id}"

        return DeviceInfo(
            identifiers={(DOMAIN, f"system_{self._system_id}")},
            name=name,
            manufacturer=MANUFACTURER,
            model="Tigo System",
            sw_version=_system_sw_version(system),
            configuration_url="https://ei.tigoenergy.com",
        )


class TigoSystemSensor(TigoBaseEntity):
    """System-level metrics and freshness sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(
            entry=entry,
            runtime=runtime,
            coordinator=runtime.summary_coordinator,
            system_id=system_id,
        )
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_system_{system_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._runtime.summary_coordinator.data.systems.get(self._system_id) is not None

    @property
    def native_value(self) -> Any:
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        if system is None:
            return None

        if self.entity_description.key == "freshness_timestamp":
            return system.freshest_timestamp
        if self.entity_description.key == "telemetry_lag_minutes":
            return _seconds_to_minutes(system.telemetry_lag_seconds)
        if self.entity_description.key == "heartbeat_age_minutes":
            return _seconds_to_minutes(system.heartbeat_age_seconds)
        if self.entity_description.key == "active_alert_count":
            return system.alert_state.active_count
        if self.entity_description.key == "system_status":
            return system.system_status
        if self.entity_description.key == "recent_alert_count":
            return system.recent_alert_count
        if self.entity_description.key == "has_monitored_modules":
            return system.has_monitored_modules
        if self.entity_description.key == "latest_alert_title":
            latest = system.alert_state.latest_active_alert
            return latest.title if latest else None
        if self.entity_description.key == "latest_alert_code":
            latest = system.alert_state.latest_active_alert
            return latest.unique_id if latest else None
        if self.entity_description.key == "latest_alert_time":
            latest = system.alert_state.latest_active_alert
            if latest is None:
                return None
            return latest.generated or latest.added

        value = system.summary.get(self.entity_description.key)

        if self.entity_description.key in {"daily_energy_dc", "ytd_energy_dc", "lifetime_energy_dc"}:
            return _to_kwh(value)

        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        if self.entity_description.key in {"telemetry_lag_minutes", "heartbeat_age_minutes"}:
            attrs.update(
                {
                    ATTR_TELEMETRY_LAG_STATUS: system.telemetry_lag_status if system else None,
                    ATTR_TELEMETRY_LAG_STATUS_RAW: (
                        system.telemetry_lag_status_raw if system else None
                    ),
                    ATTR_LAG_WARNING_MINUTES: LAG_WARNING_MINUTES,
                    ATTR_LAG_CRITICAL_MINUTES: LAG_CRITICAL_MINUTES,
                    ATTR_LATEST_SOURCE_CHECKIN: system.latest_source_checkin if system else None,
                    ATTR_LATEST_NON_EMPTY_TELEMETRY_TIMESTAMP: (
                        system.latest_non_empty_telemetry_timestamp if system else None
                    ),
                }
            )

        if self.entity_description.key in {
            "system_status",
            "recent_alert_count",
            "has_monitored_modules",
            "active_alert_count",
            "latest_alert_title",
            "latest_alert_code",
            "latest_alert_time",
        }:
            attrs.update(_alert_attributes(system.alert_state if system else None))
        return attrs


class TigoSourceSensor(TigoBaseEntity):
    """Per-source health and identity sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        source_id: str,
        source_name: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(
            entry=entry,
            runtime=runtime,
            coordinator=runtime.summary_coordinator,
            system_id=system_id,
        )
        self._source_id = source_id
        self._source_name = source_name
        self.entity_description = description

        self._attr_unique_id = (
            f"{entry.entry_id}_source_{system_id}_{source_id}_{description.key}"
        )
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_entity_category = description.entity_category

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return (
            _find_source(self._runtime.summary_coordinator.data, self._system_id, self._source_id)
            is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"source_{self._system_id}_{self._source_id}")},
            name=self._source_name,
            manufacturer=MANUFACTURER,
            model="Tigo Source",
            via_device=(DOMAIN, f"system_{self._system_id}"),
        )

    @property
    def native_value(self) -> Any:
        source = _find_source(self._runtime.summary_coordinator.data, self._system_id, self._source_id)
        if source is None:
            return None
        return getattr(source, self.entity_description.key)


class TigoArraySensor(TigoBaseEntity):
    """Per-array derived telemetry and diagnostics sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        array_id: str,
        description: SensorEntityDescription,
    ) -> None:
        coordinator = runtime.module_coordinator
        if coordinator is None:
            raise RuntimeError("Module coordinator is not available")

        super().__init__(
            entry=entry,
            runtime=runtime,
            coordinator=coordinator,
            system_id=system_id,
        )
        self._array_id = array_id
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_array_{system_id}_{array_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category
        self._attr_suggested_object_id = _array_suggested_object_id(
            system_id=system_id,
            array_id=array_id,
            metric=description.key,
        )

    @property
    def available(self) -> bool:
        if self._runtime.module_coordinator is None:
            return False
        if not super().available:
            return False
        return self._array is not None

    @property
    def device_info(self) -> DeviceInfo:
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        system_name = system.name if system else f"System {self._system_id}"
        array = self._array
        array_name = array.name if array else f"Array {self._array_id}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"array_{self._system_id}_{self._array_id}")},
            name=f"{system_name} {array_name}",
            manufacturer=MANUFACTURER,
            model="Tigo Array",
            via_device=(DOMAIN, f"system_{self._system_id}"),
        )

    @property
    def native_value(self) -> Any:
        array = self._array
        if array is None:
            return None

        latest_pin_timestamp = self._latest_panel_pin_timestamp(array)
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        telemetry_lag_seconds = _array_telemetry_lag_seconds(system, latest_pin_timestamp)

        pin_values = self._metric_values(array, "Pin")
        vin_values = self._metric_values(array, "Vin")
        iin_values = self._metric_values(array, "Iin")
        rssi_values = self._metric_values(array, "RSSI")
        watch_threshold, alert_threshold = _rssi_thresholds_from_entry(self._entry)
        reporting_module_count = self._reporting_module_count(array)
        module_count = len(array.panel_labels)

        key = self.entity_description.key
        if key == "array_power":
            return round(sum(pin_values), 1) if pin_values else None
        if key == "array_voltage":
            return round(sum(vin_values), 2) if vin_values else None
        if key == "array_voltage_average":
            return _mean_or_none(vin_values, precision=2)
        if key == "array_voltage_min":
            return round(min(vin_values), 2) if vin_values else None
        if key == "array_voltage_max":
            return round(max(vin_values), 2) if vin_values else None
        if key == "array_current_average":
            return _mean_or_none(iin_values, precision=2)
        if key == "array_current_min":
            return round(min(iin_values), 2) if iin_values else None
        if key == "array_current_max":
            return round(max(iin_values), 2) if iin_values else None
        if key == "array_rssi_average":
            return _mean_or_none(rssi_values, precision=1)
        if key == "array_rssi_worst":
            return min(rssi_values) if rssi_values else None
        if key == "array_rssi_low_count":
            return sum(1 for value in rssi_values if value < alert_threshold)
        if key == "array_rssi_watch_count":
            return sum(1 for value in rssi_values if alert_threshold <= value < watch_threshold)
        if key == "array_module_count":
            return module_count
        if key == "array_reporting_module_count":
            return reporting_module_count
        if key == "array_reporting_coverage":
            if module_count == 0:
                return None
            return round((reporting_module_count / module_count) * 100, 1)
        if key == "array_latest_stable_panel_data_timestamp":
            return latest_pin_timestamp
        if key == "array_telemetry_lag_minutes":
            return _seconds_to_minutes(telemetry_lag_seconds)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        array = self._array
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        module_freshness = (
            self._runtime.module_coordinator.data.freshness if self._runtime.module_coordinator else None
        )
        stale_threshold_seconds = _stale_threshold_seconds_from_entry(self._entry)
        if array is None:
            attrs.update(
                {
                    "array_id": self._array_id,
                    "array_name": None,
                    "array_short_label": None,
                    "array_string_id": None,
                    "array_panel_labels": [],
                    "array_module_count": 0,
                    "array_reporting_module_count": 0,
                    ATTR_ARRAY_PANEL_DATA_AGE_SECONDS: None,
                    ATTR_ARRAY_PANEL_DATA_IS_STALE: True,
                    ATTR_ARRAY_TELEMETRY_LAG_STATUS: "unknown",
                    ATTR_ARRAY_LAG_WARNING_MINUTES: LAG_WARNING_MINUTES,
                    ATTR_ARRAY_LAG_CRITICAL_MINUTES: LAG_CRITICAL_MINUTES,
                    ATTR_ARRAY_LATEST_SOURCE_CHECKIN: (
                        system.latest_source_checkin if system else None
                    ),
                    ATTR_ARRAY_LATEST_NON_EMPTY_PANEL_TIMESTAMP: None,
                    ATTR_ARRAY_LAG_BASIS: "Pin",
                }
            )
            return attrs

        reporting_count = self._reporting_module_count(array)
        latest_pin_timestamp = self._latest_panel_pin_timestamp(array)
        array_panel_data_age_seconds = (
            max(0.0, (module_freshness.fetched_at - latest_pin_timestamp).total_seconds())
            if module_freshness and latest_pin_timestamp
            else None
        )
        array_panel_data_is_stale = (
            array_panel_data_age_seconds is None
            or array_panel_data_age_seconds > stale_threshold_seconds
        )
        telemetry_lag_seconds = _array_telemetry_lag_seconds(system, latest_pin_timestamp)
        array_telemetry_lag_status = _lag_status_for_seconds(telemetry_lag_seconds)
        attrs.update(
            {
                "array_id": array.array_id,
                "array_name": array.name,
                "array_short_label": array.short_label,
                "array_string_id": array.string_id,
                "array_mppt_label": array.mppt_label,
                "array_inverter_label": array.inverter_label,
                "array_panel_labels": list(array.panel_labels),
                "array_module_count": len(array.panel_labels),
                "array_reporting_module_count": reporting_count,
                "array_reporting_module_labels": _reporting_module_labels(
                    runtime=self._runtime,
                    system_id=self._system_id,
                    panel_labels=array.panel_labels,
                ),
                ATTR_ARRAY_PANEL_DATA_AGE_SECONDS: array_panel_data_age_seconds,
                ATTR_ARRAY_PANEL_DATA_IS_STALE: array_panel_data_is_stale,
                ATTR_ARRAY_TELEMETRY_LAG_STATUS: array_telemetry_lag_status,
                ATTR_ARRAY_LAG_WARNING_MINUTES: LAG_WARNING_MINUTES,
                ATTR_ARRAY_LAG_CRITICAL_MINUTES: LAG_CRITICAL_MINUTES,
                ATTR_ARRAY_LATEST_SOURCE_CHECKIN: (
                    system.latest_source_checkin if system else None
                ),
                ATTR_ARRAY_LATEST_NON_EMPTY_PANEL_TIMESTAMP: latest_pin_timestamp,
                ATTR_ARRAY_LAG_BASIS: "Pin",
            }
        )
        return attrs

    def _latest_panel_pin_timestamp(self, array: ArraySnapshot) -> datetime | None:
        """Return latest non-empty Pin timestamp for one array."""
        if self._runtime.module_coordinator is None:
            return None
        modules = self._runtime.module_coordinator.data.by_system.get(self._system_id, {})
        timestamps: list[datetime] = []
        for panel_label in array.panel_labels:
            point = modules.get(panel_label, {}).get("Pin")
            if point is None:
                continue
            timestamps.append(point.timestamp)
        if not timestamps:
            return None
        return max(timestamps)

    def _metric_values(self, array: ArraySnapshot, metric: str) -> list[float]:
        """Return metric values for modules that belong to this array."""
        if self._runtime.module_coordinator is None:
            return []
        modules = self._runtime.module_coordinator.data.by_system.get(self._system_id, {})
        values: list[float] = []
        for panel_label in array.panel_labels:
            point = modules.get(panel_label, {}).get(metric)
            if point is None:
                continue
            values.append(point.value)
        return values

    def _reporting_module_count(self, array: ArraySnapshot) -> int:
        """Return count of modules with at least one telemetry metric in snapshot."""
        if self._runtime.module_coordinator is None:
            return 0
        modules = self._runtime.module_coordinator.data.by_system.get(self._system_id, {})
        return sum(1 for panel_label in array.panel_labels if modules.get(panel_label))

    @property
    def _array(self) -> ArraySnapshot | None:
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        if system is None:
            return None
        return system.arrays.get(self._array_id)


class TigoModuleSensor(TigoBaseEntity):
    """Per-module telemetry sensor."""

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        module_id: str,
        metric: str,
    ) -> None:
        coordinator = runtime.module_coordinator
        if coordinator is None:
            raise RuntimeError("Module coordinator is not available")

        super().__init__(
            entry=entry,
            runtime=runtime,
            coordinator=coordinator,
            system_id=system_id,
        )
        self._module_id = module_id
        self._metric = metric
        self._attr_unique_id = f"{entry.entry_id}_module_{system_id}_{module_id}_{metric}"
        self._attr_translation_key = f"module_{metric.lower()}"
        self._attr_native_unit_of_measurement = MODULE_METRIC_UNITS.get(metric)
        self._attr_device_class = MODULE_METRIC_DEVICE_CLASSES.get(metric)
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_object_id = _module_suggested_object_id(
            system_id=system_id,
            module_id=module_id,
            metric=metric,
        )

    @property
    def device_info(self) -> DeviceInfo:
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        system_name = system.name if system else f"System {self._system_id}"
        array = _array_for_module(system, self._module_id)
        via_device = (
            (DOMAIN, f"array_{self._system_id}_{array.array_id}")
            if array is not None
            else (DOMAIN, f"system_{self._system_id}")
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"module_{self._system_id}_{self._module_id}")},
            name=f"{system_name} Panel {self._module_id}",
            manufacturer=MANUFACTURER,
            model="Tigo Panel",
            via_device=via_device,
        )

    @property
    def available(self) -> bool:
        if self._runtime.module_coordinator is None:
            return False
        return super().available

    @property
    def native_value(self) -> Any:
        point = self._point
        return point.value if point else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        point = self._point
        module_freshness = (
            self._runtime.module_coordinator.data.freshness if self._runtime.module_coordinator else None
        )
        rssi_watch_threshold, rssi_alert_threshold = _rssi_thresholds_from_entry(self._entry)
        stale_threshold_seconds = _stale_threshold_seconds_from_entry(self._entry)
        system = self._runtime.summary_coordinator.data.systems.get(self._system_id)
        raw_module_id = _raw_module_id_for_label(system, self._module_id)
        module_data_age_seconds = (
            max(0.0, (module_freshness.fetched_at - point.timestamp).total_seconds())
            if module_freshness and point
            else None
        )
        module_data_is_stale = (
            module_data_age_seconds is None or module_data_age_seconds > stale_threshold_seconds
        )
        attrs.update(
            {
                "module_id": self._module_id,
                "raw_module_id": raw_module_id,
                "metric": self._metric,
                ATTR_MODULE_DATA_TIMESTAMP: point.timestamp if point else None,
                "module_latest_timestamp": point.timestamp if point else None,
                ATTR_MODULE_DATA_AGE_SECONDS: module_data_age_seconds,
                "module_data_lag_seconds": module_freshness.lag_seconds if module_freshness else None,
                ATTR_MODULE_DATA_IS_STALE: module_data_is_stale,
            }
        )
        array = _array_for_module(system, self._module_id)
        attrs["array_id"] = array.array_id if array else None
        attrs["array_name"] = array.name if array else None
        if self._metric == "RSSI":
            attrs.update(
                {
                    "rssi_scale": "0-255",
                    "rssi_watch_threshold": rssi_watch_threshold,
                    "rssi_alert_threshold": rssi_alert_threshold,
                    "rssi_status": _rssi_status_label(
                        point.value if point else None,
                        watch_threshold=rssi_watch_threshold,
                        alert_threshold=rssi_alert_threshold,
                    ),
                }
            )
        return attrs

    @property
    def _point(self) -> ModulePoint | None:
        if self._runtime.module_coordinator is None:
            return None
        return self._runtime.module_coordinator.data.points_by_key.get(
            (self._system_id, self._module_id, self._metric)
        )


class TigoRssiAggregateSensor(TigoBaseEntity):
    """System-level aggregate sensor for RSSI health."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        description: SensorEntityDescription,
    ) -> None:
        coordinator = runtime.module_coordinator
        if coordinator is None:
            raise RuntimeError("Module coordinator is not available")

        super().__init__(
            entry=entry,
            runtime=runtime,
            coordinator=coordinator,
            system_id=system_id,
        )
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_system_{system_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category

    @property
    def available(self) -> bool:
        if self._runtime.module_coordinator is None:
            return False
        return super().available

    @property
    def native_value(self) -> Any:
        rssi_values = _rssi_values_for_system(self._runtime, self._system_id)
        if self.entity_description.key == "worst_rssi":
            return min(rssi_values) if rssi_values else None

        watch_threshold, alert_threshold = _rssi_thresholds_from_entry(self._entry)
        if self.entity_description.key == "low_rssi_module_count":
            return sum(1 for value in rssi_values if value < alert_threshold)
        if self.entity_description.key == "watch_rssi_module_count":
            return sum(1 for value in rssi_values if alert_threshold <= value < watch_threshold)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        watch_threshold, alert_threshold = _rssi_thresholds_from_entry(self._entry)
        attrs.update(
            {
                "rssi_scale": "0-255",
                "rssi_watch_threshold": watch_threshold,
                "rssi_alert_threshold": alert_threshold,
            }
        )
        return attrs


def _find_source(data: SummarySnapshot, system_id: int, source_id: str) -> SourceSnapshot | None:
    system = data.systems.get(system_id)
    if system is None:
        return None
    for source in system.sources:
        if source.source_id == source_id:
            return source
    return None


def _system_sw_version(system: SystemSnapshot | None) -> str | None:
    if system is None:
        return None
    for source in system.sources:
        if source.sw_version:
            return source.sw_version
    return None


def _alert_attributes(alert_state: SystemAlertState | None) -> dict[str, Any]:
    """Return standardized alert attributes for alert sensors."""
    latest = alert_state.latest_active_alert if alert_state else None
    return {
        ATTR_ALERTS_SUPPORTED: alert_state.alerts_supported if alert_state else False,
        ATTR_LATEST_ALERT_ID: latest.alert_id if latest else None,
        ATTR_LATEST_ALERT_UNIQUE_ID: latest.unique_id if latest else None,
        ATTR_LATEST_ALERT_MESSAGE: latest.message if latest else None,
        ATTR_LATEST_ALERT_DESCRIPTION_HTML: latest.description_html if latest else None,
        ATTR_LATEST_ALERT_ARCHIVED: latest.archived if latest else None,
    }


def _to_kwh(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value) / 1000, 3)
    except (TypeError, ValueError):
        return None


def _seconds_to_minutes(value: float | None) -> float | None:
    """Convert seconds to one-decimal minutes for diagnostics display."""
    if value is None:
        return None
    return round(value / 60, 1)


def _lag_status_for_seconds(value: float | None) -> str:
    """Return lag status bucket for one lag value in seconds."""
    if value is None:
        return "unknown"
    lag_minutes = value / 60
    if lag_minutes >= LAG_CRITICAL_MINUTES:
        return "critical"
    if lag_minutes >= LAG_WARNING_MINUTES:
        return "warning"
    return "ok"


def _array_telemetry_lag_seconds(
    system: SystemSnapshot | None,
    latest_panel_timestamp: datetime | None,
) -> float | None:
    """Return array telemetry lag in seconds from latest source check-in to latest panel Pin."""
    if system is None:
        return None
    if system.latest_source_checkin is None or latest_panel_timestamp is None:
        return None
    return max(0.0, (system.latest_source_checkin - latest_panel_timestamp).total_seconds())


def _mean_or_none(values: list[float], *, precision: int) -> float | None:
    """Return rounded mean for list or None when empty."""
    if not values:
        return None
    return round(sum(values) / len(values), precision)


def _array_for_module(system: SystemSnapshot | None, module_id: str) -> ArraySnapshot | None:
    """Return array snapshot for a module/panel label when available."""
    if system is None:
        return None
    array_id = system.module_array_map.get(module_id)
    if array_id is None:
        return None
    return system.arrays.get(array_id)


def _raw_module_id_for_label(system: SystemSnapshot | None, module_id: str) -> str | None:
    """Return raw module/object-style ID for a semantic panel label when available."""
    if system is None:
        return module_id if module_id.isdigit() else None

    # If the module id itself is raw, return it unchanged.
    if module_id in system.module_label_map:
        return module_id

    candidates = [
        raw_id
        for raw_id, semantic_label in system.module_label_map.items()
        if semantic_label == module_id
    ]
    if not candidates:
        return module_id if module_id.isdigit() else None

    numeric_candidates = [candidate for candidate in candidates if candidate.isdigit()]
    pool = numeric_candidates or candidates
    # Prefer longer numeric IDs (typically object_id-style), then lexical order.
    return sorted(pool, key=lambda value: (-len(value), value))[0]


def _system_panel_labels(system: SystemSnapshot | None) -> tuple[str, ...]:
    """Return known panel labels for one system from topology and mappings."""
    if system is None:
        return ()

    labels: set[str] = set()
    for array in system.arrays.values():
        labels.update(array.panel_labels)

    for label in system.module_label_map.values():
        if label and PANEL_LABEL_PATTERN.match(label):
            labels.add(label)

    for module_id in system.module_array_map:
        if PANEL_LABEL_PATTERN.match(module_id):
            labels.add(module_id)

    return tuple(sorted(labels, key=_panel_sort_key))


def _panel_sort_key(label: str) -> tuple[str, int, str]:
    """Sort panel labels naturally (A1, A2, A10) while handling unknown formats."""
    match = re.match(r"^([A-Za-z]+)(\d+)$", label)
    if match:
        return (match.group(1).upper(), int(match.group(2)), label.upper())
    return (label.upper(), 0, label.upper())


def _reporting_module_labels(
    *,
    runtime: TigoRuntimeData,
    system_id: int,
    panel_labels: tuple[str, ...],
) -> list[str]:
    """Return sorted panel labels that currently have module telemetry points."""
    if runtime.module_coordinator is None:
        return []
    modules = runtime.module_coordinator.data.by_system.get(system_id, {})
    return sorted(label for label in panel_labels if modules.get(label))


def _rssi_values_for_system(runtime: TigoRuntimeData, system_id: int) -> list[float]:
    """Return latest RSSI values for all modules in one system."""
    if runtime.module_coordinator is None:
        return []
    modules = runtime.module_coordinator.data.by_system.get(system_id, {})
    values: list[float] = []
    for module_metrics in modules.values():
        point = module_metrics.get("RSSI")
        if point is None:
            continue
        values.append(point.value)
    return values


def _rssi_thresholds_from_entry(entry: ConfigEntry) -> tuple[int, int]:
    """Return configured RSSI watch/alert thresholds."""
    watch_threshold = int(entry.options.get(OPT_RSSI_WATCH_THRESHOLD, DEFAULT_RSSI_WATCH_THRESHOLD))
    alert_threshold = int(entry.options.get(OPT_RSSI_ALERT_THRESHOLD, DEFAULT_RSSI_ALERT_THRESHOLD))
    return watch_threshold, alert_threshold


def _rssi_status_label(
    value: float | None,
    *,
    watch_threshold: int,
    alert_threshold: int,
) -> str | None:
    """Return RSSI status label from configured thresholds."""
    if value is None:
        return None
    if value < alert_threshold:
        return "alert"
    if value < watch_threshold:
        return "watch"
    return "good"


def _stale_threshold_seconds_from_entry(entry: ConfigEntry) -> int:
    """Return configured stale threshold in seconds."""
    return int(entry.options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS))


def _module_suggested_object_id(*, system_id: int, module_id: str, metric: str) -> str:
    """Return deterministic object_id to prevent cross-system panel slug collisions."""
    panel_token = _sanitize_object_token(module_id)
    metric_token = _sanitize_object_token(metric)
    return f"system_{system_id}_panel_{panel_token}_{metric_token}"


def _array_suggested_object_id(*, system_id: int, array_id: str, metric: str) -> str:
    """Return deterministic object_id for derived array sensors."""
    array_token = _sanitize_object_token(array_id)
    metric_token = _sanitize_object_token(metric)
    return f"system_{system_id}_array_{array_token}_{metric_token}"


def _sanitize_object_token(value: str) -> str:
    """Sanitize one object-id token to lowercase ascii with underscores."""
    normalized = OBJECT_TOKEN_PATTERN.sub("_", value.strip().lower()).strip("_")
    return normalized or "unknown"
