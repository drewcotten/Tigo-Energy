"""Binary sensor platform for the Tigo Energy integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DATA_LAG_SECONDS,
    ATTR_IS_STALE,
    ATTR_LATEST_STABLE_TIMESTAMP,
    ATTR_SYSTEM_DATA_AGE_SECONDS,
    ATTR_SYSTEM_DATA_IS_STALE,
    ATTR_SYSTEM_DATA_TIMESTAMP,
    DOMAIN,
    MANUFACTURER,
)
from .models import SummarySnapshot, SystemSnapshot, TigoRuntimeData
from .sensor import _alert_attributes, _system_sw_version


@dataclass(frozen=True, slots=True)
class AlertBinaryDescription:
    """Description of one alert-related binary sensor."""

    key: str
    translation_key: str
    entity_category: EntityCategory | None = None


ALERT_BINARY_SENSORS: tuple[AlertBinaryDescription, ...] = (
    AlertBinaryDescription(
        key="pv_off_active",
        translation_key="pv_off_active",
    ),
    AlertBinaryDescription(
        key="string_shutdown_active",
        translation_key="string_shutdown_active",
    ),
)


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors from a config entry."""
    runtime: TigoRuntimeData = entry.runtime_data

    def _async_add_grouped(entities: list[TigoAlertBinarySensor]) -> None:
        groups: dict[str | None, list[TigoAlertBinarySensor]] = {}
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

    manager = TigoAlertBinaryEntityManager(entry, runtime, _async_add_grouped)

    entities = manager.collect_initial_entities()
    if entities:
        _async_add_grouped(entities)

    entry.async_on_unload(
        runtime.summary_coordinator.async_add_listener(manager.handle_summary_update)
    )


class TigoAlertBinaryEntityManager:
    """Track known binary sensors and add entities for newly discovered systems."""

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        async_add_entities: Callable[[list[TigoAlertBinarySensor]], None],
    ) -> None:
        self._entry = entry
        self._runtime = runtime
        self._async_add_entities = async_add_entities
        self._known_keys: set[tuple[int, str]] = set()

    def collect_initial_entities(self) -> list[TigoAlertBinarySensor]:
        """Collect initial alert binary sensors."""
        system_ids = set(self._runtime.tracked_system_ids) | set(
            self._runtime.summary_coordinator.data.systems
        )
        return self._new_entities(system_ids)

    def handle_summary_update(self) -> None:
        """Add sensors for newly discovered systems on summary refresh."""
        system_ids = set(self._runtime.tracked_system_ids) | set(
            self._runtime.summary_coordinator.data.systems
        )
        new_entities = self._new_entities(system_ids)
        if new_entities:
            self._async_add_entities(new_entities)

    def _new_entities(self, system_ids: set[int]) -> list[TigoAlertBinarySensor]:
        new_entities: list[TigoAlertBinarySensor] = []
        for system_id in sorted(system_ids):
            for description in ALERT_BINARY_SENSORS:
                key = (system_id, description.key)
                if key in self._known_keys:
                    continue
                self._known_keys.add(key)
                new_entities.append(
                    TigoAlertBinarySensor(
                        entry=self._entry,
                        runtime=self._runtime,
                        system_id=system_id,
                        description=description,
                    )
                )
        return new_entities


class TigoAlertBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for PV-Off and shutdown states."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry: ConfigEntry,
        runtime: TigoRuntimeData,
        system_id: int,
        description: AlertBinaryDescription,
    ) -> None:
        super().__init__(runtime.summary_coordinator)
        self._entry = entry
        self._runtime = runtime
        self._system_id = system_id
        self.entity_description = description

        self._attr_unique_id = f"{entry.entry_id}_system_{system_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_entity_category = description.entity_category

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self._system is not None

    @property
    def is_on(self) -> bool | None:
        system = self._system
        if system is None:
            return None

        if self.entity_description.key == "pv_off_active":
            return system.alert_state.pv_off_active
        if self.entity_description.key == "string_shutdown_active":
            return system.alert_state.string_shutdown_active
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._runtime.summary_coordinator.data
        system = self._system
        attrs = {
            ATTR_LATEST_STABLE_TIMESTAMP: summary.freshness.latest_stable_timestamp,
            ATTR_IS_STALE: summary.freshness.is_stale,
            ATTR_DATA_LAG_SECONDS: summary.freshness.lag_seconds,
            ATTR_SYSTEM_DATA_TIMESTAMP: system.freshest_timestamp if system else None,
            ATTR_SYSTEM_DATA_AGE_SECONDS: system.system_data_age_seconds if system else None,
            ATTR_SYSTEM_DATA_IS_STALE: system.system_data_is_stale if system else True,
        }
        attrs.update(_alert_attributes(system.alert_state if system else None))
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        system = self._system
        name = system.name if system else f"System {self._system_id}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"system_{self._system_id}")},
            name=name,
            manufacturer=MANUFACTURER,
            model="Tigo System",
            sw_version=_system_sw_version(system),
            configuration_url="https://ei.tigoenergy.com",
        )

    @property
    def _system(self) -> SystemSnapshot | None:
        data: SummarySnapshot = self._runtime.summary_coordinator.data
        return data.systems.get(self._system_id)
