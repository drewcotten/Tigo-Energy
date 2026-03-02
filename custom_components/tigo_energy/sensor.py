"""Sensor platform for the Tigo Energy integration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
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
    ATTR_LATEST_SOURCE_CHECKIN,
    ATTR_LATEST_STABLE_TIMESTAMP,
    ATTR_MODULE_DATA_AGE_SECONDS,
    ATTR_MODULE_DATA_IS_STALE,
    ATTR_MODULE_DATA_TIMESTAMP,
    ATTR_SYSTEM_DATA_AGE_SECONDS,
    ATTR_SYSTEM_DATA_IS_STALE,
    ATTR_SYSTEM_DATA_TIMESTAMP,
    ATTR_TELEMETRY_LAG_STATUS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DOMAIN,
    LAG_CRITICAL_MINUTES,
    LAG_WARNING_MINUTES,
    MANUFACTURER,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
)
from .coordinator import METRICS
from .models import (
    ModulePoint,
    ModuleSnapshot,
    SourceSnapshot,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
    TigoRuntimeData,
)

OBJECT_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SystemMetricDescription:
    """Description of one system-level metric sensor."""

    key: str
    translation_key: str
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None


@dataclass(frozen=True, slots=True)
class SourceMetricDescription:
    """Description of one source-level metric sensor."""

    key: str
    translation_key: str
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    entity_category: EntityCategory | None = None


@dataclass(frozen=True, slots=True)
class RssiAggregateMetricDescription:
    """Description of one RSSI aggregate sensor."""

    key: str
    translation_key: str
    unit: str | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None


SYSTEM_METRICS: tuple[SystemMetricDescription, ...] = (
    SystemMetricDescription(
        key="last_power_dc",
        translation_key="current_power",
        device_class=SensorDeviceClass.POWER,
        unit=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SystemMetricDescription(
        key="daily_energy_dc",
        translation_key="daily_energy",
        device_class=SensorDeviceClass.ENERGY,
        unit="kWh",
        state_class=SensorStateClass.TOTAL,
    ),
    SystemMetricDescription(
        key="ytd_energy_dc",
        translation_key="ytd_energy",
        device_class=SensorDeviceClass.ENERGY,
        unit="kWh",
        state_class=SensorStateClass.TOTAL,
    ),
    SystemMetricDescription(
        key="lifetime_energy_dc",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        unit="kWh",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SystemMetricDescription(
        key="freshness_timestamp",
        translation_key="latest_stable_data_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SystemMetricDescription(
        key="telemetry_lag_minutes",
        translation_key="telemetry_lag_minutes",
        unit=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="heartbeat_age_minutes",
        translation_key="heartbeat_age_minutes",
        unit=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

ALERT_METRICS: tuple[SystemMetricDescription, ...] = (
    SystemMetricDescription(
        key="system_status",
        translation_key="system_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="recent_alert_count",
        translation_key="recent_alert_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="has_monitored_modules",
        translation_key="has_monitored_modules",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="active_alert_count",
        translation_key="active_alert_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="latest_alert_title",
        translation_key="latest_alert_title",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="latest_alert_code",
        translation_key="latest_alert_code",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SystemMetricDescription(
        key="latest_alert_time",
        translation_key="latest_alert_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

RSSI_AGGREGATE_METRICS: tuple[RssiAggregateMetricDescription, ...] = (
    RssiAggregateMetricDescription(
        key="low_rssi_module_count",
        translation_key="low_rssi_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RssiAggregateMetricDescription(
        key="watch_rssi_module_count",
        translation_key="watch_rssi_module_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RssiAggregateMetricDescription(
        key="worst_rssi",
        translation_key="worst_module_rssi",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

SOURCE_METRICS: tuple[SourceMetricDescription, ...] = (
    SourceMetricDescription(
        key="last_checkin",
        translation_key="source_last_checkin",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SourceMetricDescription(
        key="control_state",
        translation_key="source_control_state",
    ),
    SourceMetricDescription(
        key="sw_version",
        translation_key="source_sw_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SourceMetricDescription(
        key="gateway_count",
        translation_key="source_gateway_count",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SourceMetricDescription(
        key="serial",
        translation_key="source_serial",
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

    def collect_initial_entities(self) -> list[SensorEntity]:
        """Collect initial entities from current coordinator data."""
        entities: list[SensorEntity] = []
        summary_data = self._runtime.summary_coordinator.data
        module_data = self._runtime.module_coordinator.data if self._runtime.module_coordinator else None
        system_ids = self._candidate_system_ids(summary_data, module_data)

        entities.extend(self._new_system_entities(system_ids))
        entities.extend(self._new_source_entities(summary_data))

        if module_data is not None:
            entities.extend(self._new_module_entities(module_data))
            entities.extend(self._new_rssi_aggregate_entities(system_ids))

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
            new_entities.extend(self._new_rssi_aggregate_entities(system_ids))
        if new_entities:
            self._async_add_entities(new_entities)

    def handle_module_update(self) -> None:
        """Add entities for newly discovered modules."""
        if self._runtime.module_coordinator is None:
            return

        module_data = self._runtime.module_coordinator.data
        system_ids = self._candidate_system_ids(self._runtime.summary_coordinator.data, module_data)
        new_entities = self._new_system_entities(system_ids)
        new_entities.extend(self._new_module_entities(module_data))
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

    def _new_module_entities(self, data: ModuleSnapshot) -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []
        for system_id, modules in data.by_system.items():
            for module_id, metrics in modules.items():
                for metric in METRICS:
                    if metric not in metrics:
                        continue
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

    def _new_rssi_aggregate_entities(self, system_ids: set[int]) -> list[SensorEntity]:
        """Create RSSI aggregate entities for systems."""
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
        return {
            ATTR_LATEST_STABLE_TIMESTAMP: freshness.latest_stable_timestamp,
            ATTR_IS_STALE: freshness.is_stale,
            ATTR_DATA_LAG_SECONDS: freshness.lag_seconds,
            ATTR_SYSTEM_DATA_TIMESTAMP: system.freshest_timestamp if system else None,
            ATTR_SYSTEM_DATA_AGE_SECONDS: system.system_data_age_seconds if system else None,
            ATTR_SYSTEM_DATA_IS_STALE: system.system_data_is_stale if system else True,
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

    entity_description: SystemMetricDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        description: SystemMetricDescription,
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
        self._attr_native_unit_of_measurement = description.unit
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

    entity_description: SourceMetricDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        source_id: str,
        source_name: str,
        description: SourceMetricDescription,
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
        self._attr_native_unit_of_measurement = description.unit
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
        return DeviceInfo(
            identifiers={(DOMAIN, f"module_{self._system_id}_{self._module_id}")},
            name=f"{system_name} Panel {self._module_id}",
            manufacturer=MANUFACTURER,
            model="Tigo Panel",
            via_device=(DOMAIN, f"system_{self._system_id}"),
        )

    @property
    def available(self) -> bool:
        if self._runtime.module_coordinator is None:
            return False
        if not super().available:
            return False

        return self._point is not None

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
                "metric": self._metric,
                ATTR_MODULE_DATA_TIMESTAMP: point.timestamp if point else None,
                "module_latest_timestamp": point.timestamp if point else None,
                ATTR_MODULE_DATA_AGE_SECONDS: module_data_age_seconds,
                "module_data_lag_seconds": module_freshness.lag_seconds if module_freshness else None,
                ATTR_MODULE_DATA_IS_STALE: module_data_is_stale,
            }
        )
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

    entity_description: RssiAggregateMetricDescription

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        description: RssiAggregateMetricDescription,
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
        self._attr_native_unit_of_measurement = description.unit
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


def _sanitize_object_token(value: str) -> str:
    """Sanitize one object-id token to lowercase ascii with underscores."""
    normalized = OBJECT_TOKEN_PATTERN.sub("_", value.strip().lower()).strip("_")
    return normalized or "unknown"
