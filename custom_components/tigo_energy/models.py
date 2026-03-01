"""Data models for the Tigo Energy integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


@dataclass(slots=True)
class FreshnessState:
    """Freshness and staleness state for a data stream."""

    latest_stable_timestamp: datetime | None
    fetched_at: datetime
    lag_seconds: float | None
    is_stale: bool


@dataclass(slots=True)
class ModulePoint:
    """A latest point for one module metric."""

    system_id: int
    module_id: str
    metric: str
    value: float
    timestamp: datetime


@dataclass(slots=True)
class ModuleSnapshot:
    """Module telemetry snapshot across one or many systems."""

    points_by_key: dict[tuple[int, str, str], ModulePoint]
    by_system: dict[int, dict[str, dict[str, ModulePoint]]]
    freshness: FreshnessState
    dedupe_ignored_points: int = 0


@dataclass(slots=True)
class SourceSnapshot:
    """Per-source status and identity fields."""

    source_id: str
    name: str
    serial: str | None
    control_state: str | None
    sw_version: str | None
    gateway_count: int | None
    last_checkin: datetime | None
    dataset_latest_timestamp: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SystemSnapshot:
    """System metadata + summary + source state."""

    system_id: int
    name: str
    timezone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    turn_on_date: str | None
    power_rating: float | None
    summary: dict[str, Any]
    sources: list[SourceSnapshot]
    freshest_timestamp: datetime | None


@dataclass(slots=True)
class SummarySnapshot:
    """Top-level snapshot for system+source data."""

    account_id: str
    systems: dict[int, SystemSnapshot]
    freshness: FreshnessState


@dataclass(slots=True)
class TigoSystemRuntime:
    """Runtime holder for one tracked system."""

    system_id: int
    system_name: str


@dataclass(slots=True)
class TigoRuntimeData:
    """Integration runtime data attached to ConfigEntry.runtime_data."""

    account_id: str
    entry_mode: str
    summary_coordinator: DataUpdateCoordinator[SummarySnapshot]
    module_coordinator: DataUpdateCoordinator[ModuleSnapshot] | None
    tracked_system_ids: set[int]
    connection_notifier: Any | None = None
    unsub_update_listener: Any | None = None
