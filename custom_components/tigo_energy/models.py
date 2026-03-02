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
    empty_window_fallback_attempts: int = 0
    empty_window_fallback_hits: int = 0
    future_rows_dropped: int = 0
    invalid_timestamp_rows: int = 0
    low_rssi_module_count: int = 0
    watch_rssi_module_count: int = 0
    worst_rssi: float | None = None


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
class AlertRecord:
    """One alert record from the system alert feed."""

    alert_id: int | None
    unique_id: int | None
    title: str | None
    message: str | None
    description_html: str | None
    added: datetime | None
    generated: datetime | None
    archived: bool


@dataclass(slots=True)
class SystemAlertState:
    """Computed alert and shutdown state for one system."""

    active_count: int
    latest_active_alert: AlertRecord | None
    pv_off_active: bool
    string_shutdown_active: bool
    alerts_supported: bool


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
    system_data_age_seconds: float | None
    system_data_is_stale: bool
    latest_source_checkin: datetime | None
    latest_non_empty_telemetry_timestamp: datetime | None
    heartbeat_age_seconds: float | None
    telemetry_lag_seconds: float | None
    telemetry_lag_status: str | None
    alert_state: SystemAlertState
    system_status: str | None = None
    recent_alert_count: int | None = None
    has_monitored_modules: bool | None = None
    module_label_map: dict[str, str] = field(default_factory=dict)


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
    system_subentry_ids: dict[int, str] = field(default_factory=dict)
    connection_notifier: Any | None = None
    unsub_update_listener: Any | None = None
