"""Data coordinators for Tigo Energy integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TigoApiAuthError,
    TigoApiClient,
    TigoApiConnectionError,
    TigoApiError,
    parse_tigo_aggregate_csv,
    parse_tigo_timestamp,
)
from .const import (
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    ENTRY_MODE_ALL_SYSTEMS,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_MODULE_POLL_SECONDS,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
)
from .models import (
    FreshnessState,
    ModulePoint,
    ModuleSnapshot,
    SourceSnapshot,
    SummarySnapshot,
    SystemSnapshot,
)
from .notifications import (
    CONNECTION_SOURCE_MODULES,
    CONNECTION_SOURCE_SUMMARY,
    TigoConnectionNotifier,
)

METRICS: tuple[str, ...] = ("Pin", "Vin", "Iin", "RSSI")
LOGGER = logging.getLogger(__name__)


class TigoSummaryCoordinator(DataUpdateCoordinator[SummarySnapshot]):
    """Coordinator that fetches system summary + source state."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TigoApiClient,
        entry_mode: str,
        configured_system_ids: set[int],
        options: Mapping[str, Any],
        connection_notifier: TigoConnectionNotifier | None = None,
    ) -> None:
        self._client = client
        self._entry_mode = entry_mode
        self._configured_system_ids = configured_system_ids
        self._options = options
        self._connection_notifier = connection_notifier
        self.tracked_system_ids: set[int] = set(configured_system_ids)

        interval = int(options.get(OPT_SUMMARY_POLL_SECONDS, DEFAULT_SUMMARY_POLL_SECONDS))
        super().__init__(
            hass,
            logger=LOGGER,
            name="Tigo summary",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> SummarySnapshot:
        stale_threshold = int(
            self._options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS)
        )

        try:
            list_payload = await self._client.async_list_systems()
        except TigoApiAuthError as err:
            await self._async_report_connection_recovered()
            raise ConfigEntryAuthFailed from err
        except TigoApiConnectionError as err:
            await self._async_report_connection_failure()
            raise UpdateFailed("Could not reach Tigo API") from err
        except TigoApiError as err:
            await self._async_report_connection_recovered()
            raise UpdateFailed(f"Unexpected Tigo API error: {err}") from err

        systems_from_api: dict[int, dict[str, Any]] = {}
        for record in list_payload:
            system_id = record.get("system_id")
            if system_id is None:
                continue
            systems_from_api[int(system_id)] = record

        if self._entry_mode == ENTRY_MODE_ALL_SYSTEMS:
            target_system_ids = set(systems_from_api)
        else:
            target_system_ids = set(self._configured_system_ids)

        if not target_system_ids:
            await self._async_report_connection_recovered()
            raise UpdateFailed("No Tigo systems available for this entry")

        systems: dict[int, SystemSnapshot] = {}
        global_latest: datetime | None = None

        for system_id in sorted(target_system_ids):
            try:
                details = await self._client.async_get_system(system_id)
                summary = await self._client.async_get_summary(system_id)
                sources_raw = await self._client.async_get_sources(system_id)
            except TigoApiAuthError as err:
                await self._async_report_connection_recovered()
                raise ConfigEntryAuthFailed from err
            except TigoApiConnectionError as err:
                await self._async_report_connection_failure()
                raise UpdateFailed("Could not reach Tigo API") from err
            except TigoApiError as err:
                await self._async_report_connection_recovered()
                raise UpdateFailed(f"Failed to fetch system {system_id}: {err}") from err

            source_snapshots: list[SourceSnapshot] = []
            system_latest: datetime | None = parse_tigo_timestamp(summary.get("updated_on"))

            for source in sources_raw:
                source_latest = _extract_source_latest_timestamp(source)
                last_checkin = parse_tigo_timestamp(source.get("last_checkin"))
                if source_latest and (system_latest is None or source_latest > system_latest):
                    system_latest = source_latest
                if last_checkin and (system_latest is None or last_checkin > system_latest):
                    system_latest = last_checkin

                source_snapshots.append(
                    SourceSnapshot(
                        source_id=str(source.get("source_id") or source.get("id") or source.get("serial") or "unknown"),
                        name=str(source.get("name") or source.get("serial") or f"Source {system_id}"),
                        serial=_as_optional_str(source.get("serial")),
                        control_state=_as_optional_str(source.get("control_state")),
                        sw_version=_as_optional_str(source.get("sw_version")),
                        gateway_count=_as_optional_int(source.get("gateway_count")),
                        last_checkin=last_checkin,
                        dataset_latest_timestamp=source_latest,
                        raw=source,
                    )
                )

            combined = systems_from_api.get(system_id, {})
            name = (
                _as_optional_str(details.get("name"))
                or _as_optional_str(combined.get("name"))
                or f"System {system_id}"
            )

            system_snapshot = SystemSnapshot(
                system_id=system_id,
                name=name,
                timezone=_as_optional_str(details.get("timezone") or combined.get("timezone")),
                address=_as_optional_str(details.get("address") or combined.get("address")),
                latitude=_as_optional_float(details.get("lat") or combined.get("lat")),
                longitude=_as_optional_float(details.get("long") or combined.get("long")),
                turn_on_date=_as_optional_str(
                    details.get("turn_on_date") or combined.get("turn_on_date")
                ),
                power_rating=_as_optional_float(
                    details.get("power_rating") or combined.get("power_rating")
                ),
                summary=summary,
                sources=source_snapshots,
                freshest_timestamp=system_latest,
            )

            systems[system_id] = system_snapshot

            if system_latest and (global_latest is None or system_latest > global_latest):
                global_latest = system_latest

        fetched_at = datetime.now(UTC)
        lag_seconds = (fetched_at - global_latest).total_seconds() if global_latest else None
        is_stale = bool(lag_seconds and lag_seconds > stale_threshold)

        self.tracked_system_ids = set(systems)
        await self._async_report_connection_recovered()

        account_id = self._client.account_id or "unknown"
        return SummarySnapshot(
            account_id=account_id,
            systems=systems,
            freshness=FreshnessState(
                latest_stable_timestamp=global_latest,
                fetched_at=fetched_at,
                lag_seconds=lag_seconds,
                is_stale=is_stale,
            ),
        )

    async def _async_report_connection_failure(self) -> None:
        """Show connectivity notification when this coordinator cannot reach API."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_report_connection_failure(CONNECTION_SOURCE_SUMMARY)

    async def _async_report_connection_recovered(self) -> None:
        """Dismiss connectivity notification when this coordinator recovers."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_report_connection_recovered(
            CONNECTION_SOURCE_SUMMARY
        )


class TigoModuleCoordinator(DataUpdateCoordinator[ModuleSnapshot]):
    """Coordinator that fetches module-level telemetry with lag-aware backfill."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TigoApiClient,
        summary_coordinator: TigoSummaryCoordinator,
        options: Mapping[str, Any],
        connection_notifier: TigoConnectionNotifier | None = None,
    ) -> None:
        self._client = client
        self._summary_coordinator = summary_coordinator
        self._options = options
        self._connection_notifier = connection_notifier
        self._points_by_key: dict[tuple[int, str, str], ModulePoint] = {}

        interval = int(options.get(OPT_MODULE_POLL_SECONDS, DEFAULT_MODULE_POLL_SECONDS))
        super().__init__(
            hass,
            logger=LOGGER,
            name="Tigo modules",
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> ModuleSnapshot:
        stale_threshold = int(
            self._options.get(OPT_STALE_THRESHOLD_SECONDS, DEFAULT_STALE_THRESHOLD_SECONDS)
        )
        backfill_minutes = int(
            self._options.get(OPT_BACKFILL_WINDOW_MINUTES, DEFAULT_BACKFILL_WINDOW_MINUTES)
        )
        recent_cutoff_minutes = int(
            self._options.get(OPT_RECENT_CUTOFF_MINUTES, DEFAULT_RECENT_CUTOFF_MINUTES)
        )

        system_ids = sorted(self._summary_coordinator.tracked_system_ids)
        if not system_ids:
            fetched = datetime.now(UTC)
            await self._async_report_connection_recovered()
            return ModuleSnapshot(
                points_by_key=dict(self._points_by_key),
                by_system={},
                freshness=FreshnessState(
                    latest_stable_timestamp=None,
                    fetched_at=fetched,
                    lag_seconds=None,
                    is_stale=True,
                ),
                dedupe_ignored_points=0,
            )

        window_end = datetime.now(UTC) - timedelta(minutes=recent_cutoff_minutes)
        window_start = window_end - timedelta(minutes=backfill_minutes)

        dedupe_ignored_points = 0
        latest_seen: datetime | None = None

        for system_id in system_ids:
            for metric in METRICS:
                try:
                    csv_text = await self._client.async_get_aggregate_csv(
                        system_id=system_id,
                        start=window_start,
                        end=window_end,
                        metric=metric,
                    )
                except TigoApiAuthError as err:
                    await self._async_report_connection_recovered()
                    raise ConfigEntryAuthFailed from err
                except TigoApiConnectionError as err:
                    await self._async_report_connection_failure()
                    raise UpdateFailed("Could not reach Tigo API") from err
                except TigoApiError as err:
                    await self._async_report_connection_recovered()
                    raise UpdateFailed(
                        f"Failed to fetch module metric {metric} for system {system_id}: {err}"
                    ) from err

                parsed = parse_tigo_aggregate_csv(csv_text)
                for module_id, points in parsed.items():
                    if not points:
                        continue
                    point_ts, point_value = max(points, key=lambda item: item[0])
                    key = (system_id, module_id, metric)
                    current = self._points_by_key.get(key)
                    if current and point_ts <= current.timestamp:
                        dedupe_ignored_points += 1
                        continue

                    module_point = ModulePoint(
                        system_id=system_id,
                        module_id=module_id,
                        metric=metric,
                        value=point_value,
                        timestamp=point_ts,
                    )
                    self._points_by_key[key] = module_point
                    if latest_seen is None or point_ts > latest_seen:
                        latest_seen = point_ts

        by_system: dict[int, dict[str, dict[str, ModulePoint]]] = {}
        for point in self._points_by_key.values():
            by_system.setdefault(point.system_id, {}).setdefault(point.module_id, {})[
                point.metric
            ] = point

        fetched_at = datetime.now(UTC)
        lag_seconds = (fetched_at - latest_seen).total_seconds() if latest_seen else None
        is_stale = bool(lag_seconds and lag_seconds > stale_threshold)
        await self._async_report_connection_recovered()

        return ModuleSnapshot(
            points_by_key=dict(self._points_by_key),
            by_system=by_system,
            freshness=FreshnessState(
                latest_stable_timestamp=latest_seen,
                fetched_at=fetched_at,
                lag_seconds=lag_seconds,
                is_stale=is_stale,
            ),
            dedupe_ignored_points=dedupe_ignored_points,
        )

    async def _async_report_connection_failure(self) -> None:
        """Show connectivity notification when this coordinator cannot reach API."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_report_connection_failure(CONNECTION_SOURCE_MODULES)

    async def _async_report_connection_recovered(self) -> None:
        """Dismiss connectivity notification when this coordinator recovers."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_report_connection_recovered(
            CONNECTION_SOURCE_MODULES
        )


def _extract_source_latest_timestamp(source: dict[str, Any]) -> datetime | None:
    """Extract latest dataset timestamp from source.sets[] and known keys."""
    candidates: list[datetime] = []

    direct_fields = (
        source.get("last"),
        source.get("last_update"),
        source.get("last_timestamp"),
        source.get("last_data"),
    )
    for raw in direct_fields:
        parsed = parse_tigo_timestamp(raw)
        if parsed is not None:
            candidates.append(parsed)

    for set_item in source.get("sets", []):
        if not isinstance(set_item, dict):
            continue
        for key, value in set_item.items():
            key_lower = str(key).lower()
            if "last" in key_lower or "timestamp" in key_lower or "minute" in key_lower:
                parsed = parse_tigo_timestamp(value)
                if parsed is not None:
                    candidates.append(parsed)

    if not candidates:
        return None
    return max(candidates)


def _as_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _as_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
