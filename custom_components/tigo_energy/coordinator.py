"""Data coordinators for Tigo Energy integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ParsedAggregateCsv,
    TigoApiAuthError,
    TigoApiClient,
    TigoApiConnectionError,
    TigoApiError,
    TigoApiRateLimitError,
    parse_tigo_aggregate_csv,
    parse_tigo_timestamp,
)
from .const import (
    DEFAULT_BACKFILL_WINDOW_MINUTES,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    EMPTY_WINDOW_FALLBACK_MINUTES_MAX,
    EMPTY_WINDOW_FALLBACK_MINUTES_MIN,
    ENTRY_MODE_ALL_SYSTEMS,
    LAG_CRITICAL_CONSECUTIVE_POLLS,
    LAG_CRITICAL_MINUTES,
    LAG_WARNING_MINUTES,
    MAX_FUTURE_BUCKET_MINUTES,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_MODULE_POLL_SECONDS,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
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
        self._telemetry_lag_critical_poll_streak = 0

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
        backfill_minutes = int(
            self._options.get(OPT_BACKFILL_WINDOW_MINUTES, DEFAULT_BACKFILL_WINDOW_MINUTES)
        )
        recent_cutoff_minutes = int(
            self._options.get(OPT_RECENT_CUTOFF_MINUTES, DEFAULT_RECENT_CUTOFF_MINUTES)
        )

        try:
            list_payload = await self._client.async_list_systems()
        except TigoApiRateLimitError as err:
            await self._async_report_connection_recovered()
            raise UpdateFailed("Tigo API rate limited summary polling", retry_after=err.retry_after) from err
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

        window_end = datetime.now(UTC) - timedelta(minutes=recent_cutoff_minutes)
        window_start = window_end - timedelta(minutes=backfill_minutes)

        systems: dict[int, SystemSnapshot] = {}
        global_latest: datetime | None = None
        critical_system_count = 0
        warning_system_count = 0
        worst_critical_lag_minutes: float | None = None

        for system_id in sorted(target_system_ids):
            try:
                details = await self._client.async_get_system(system_id)
                summary = await self._client.async_get_summary(system_id)
                sources_raw = await self._client.async_get_sources(system_id)
                latest_non_empty_telemetry = await self._async_fetch_combined_latest_timestamp(
                    system_id=system_id,
                    window_start=window_start,
                    window_end=window_end,
                    backfill_minutes=backfill_minutes,
                    naive_tz=_resolve_naive_timezone(
                        system_timezone=_as_optional_str(
                            details.get("timezone") or systems_from_api.get(system_id, {}).get("timezone")
                        ),
                        hass_timezone=self.hass.config.time_zone,
                    ),
                )
            except TigoApiRateLimitError as err:
                await self._async_report_connection_recovered()
                raise UpdateFailed(
                    f"Tigo API rate limited while fetching system {system_id}",
                    retry_after=err.retry_after,
                ) from err
            except TigoApiAuthError as err:
                await self._async_report_connection_recovered()
                raise ConfigEntryAuthFailed from err
            except TigoApiConnectionError as err:
                await self._async_report_connection_failure()
                raise UpdateFailed("Could not reach Tigo API") from err
            except TigoApiError as err:
                await self._async_report_connection_recovered()
                raise UpdateFailed(f"Failed to fetch system {system_id}: {err}") from err

            combined = systems_from_api.get(system_id, {})
            system_timezone = _as_optional_str(details.get("timezone") or combined.get("timezone"))

            source_snapshots: list[SourceSnapshot] = []
            system_latest: datetime | None = parse_tigo_timestamp(summary.get("updated_on"))
            latest_source_checkin: datetime | None = None

            for source in sources_raw:
                source_latest = _extract_source_latest_timestamp(source)
                last_checkin = parse_tigo_timestamp(source.get("last_checkin"))
                if source_latest and (system_latest is None or source_latest > system_latest):
                    system_latest = source_latest
                if last_checkin and (system_latest is None or last_checkin > system_latest):
                    system_latest = last_checkin
                if last_checkin and (
                    latest_source_checkin is None or last_checkin > latest_source_checkin
                ):
                    latest_source_checkin = last_checkin

                source_snapshots.append(
                    SourceSnapshot(
                        source_id=str(
                            source.get("source_id")
                            or source.get("id")
                            or source.get("serial")
                            or "unknown"
                        ),
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

            fetched_for_system = datetime.now(UTC)
            system_data_age_seconds = (
                (fetched_for_system - system_latest).total_seconds() if system_latest else None
            )
            system_data_is_stale = (
                system_data_age_seconds is None or system_data_age_seconds > stale_threshold
            )
            heartbeat_age_seconds = (
                (fetched_for_system - latest_source_checkin).total_seconds()
                if latest_source_checkin
                else None
            )
            telemetry_lag_seconds = None
            if latest_source_checkin and latest_non_empty_telemetry:
                telemetry_lag_seconds = max(
                    0.0,
                    (latest_source_checkin - latest_non_empty_telemetry).total_seconds(),
                )

            telemetry_lag_status = _telemetry_lag_status(telemetry_lag_seconds)
            if telemetry_lag_status == "critical":
                critical_system_count += 1
                lag_minutes = telemetry_lag_seconds / 60 if telemetry_lag_seconds is not None else None
                if lag_minutes is not None and (
                    worst_critical_lag_minutes is None or lag_minutes > worst_critical_lag_minutes
                ):
                    worst_critical_lag_minutes = lag_minutes
            elif telemetry_lag_status == "warning":
                warning_system_count += 1

            name = (
                _as_optional_str(details.get("name"))
                or _as_optional_str(combined.get("name"))
                or f"System {system_id}"
            )

            system_snapshot = SystemSnapshot(
                system_id=system_id,
                name=name,
                timezone=system_timezone,
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
                system_data_age_seconds=system_data_age_seconds,
                system_data_is_stale=system_data_is_stale,
                latest_source_checkin=latest_source_checkin,
                latest_non_empty_telemetry_timestamp=latest_non_empty_telemetry,
                heartbeat_age_seconds=heartbeat_age_seconds,
                telemetry_lag_seconds=telemetry_lag_seconds,
                telemetry_lag_status=telemetry_lag_status,
            )

            systems[system_id] = system_snapshot

            if system_latest and (global_latest is None or system_latest > global_latest):
                global_latest = system_latest

        fetched_at = datetime.now(UTC)
        lag_seconds = (fetched_at - global_latest).total_seconds() if global_latest else None
        is_stale = lag_seconds is None or lag_seconds > stale_threshold

        self.tracked_system_ids = set(systems)
        await self._async_report_connection_recovered()
        await self._async_handle_telemetry_lag_notifications(
            critical_system_count=critical_system_count,
            warning_system_count=warning_system_count,
            worst_critical_lag_minutes=worst_critical_lag_minutes,
        )

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

    async def _async_fetch_combined_latest_timestamp(
        self,
        *,
        system_id: int,
        window_start: datetime,
        window_end: datetime,
        backfill_minutes: int,
        naive_tz,
    ) -> datetime | None:
        """Fetch latest non-empty combined telemetry timestamp for one system."""
        primary_csv = await self._client.async_get_combined_csv(
            system_id=system_id,
            start=window_start,
            end=window_end,
            metric="Pin",
        )
        primary = parse_tigo_aggregate_csv(
            primary_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )
        if _parsed_has_points(primary):
            return _latest_timestamp(primary)

        fallback_window_minutes = _fallback_window_minutes(backfill_minutes)
        fallback_start = window_end - timedelta(minutes=fallback_window_minutes)
        fallback_csv = await self._client.async_get_combined_csv(
            system_id=system_id,
            start=fallback_start,
            end=window_end,
            metric="Pin",
        )
        fallback = parse_tigo_aggregate_csv(
            fallback_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )
        filtered = _filter_parsed_to_window(fallback, window_start=window_start, window_end=window_end)
        return _latest_timestamp(filtered)

    async def _async_handle_telemetry_lag_notifications(
        self,
        *,
        critical_system_count: int,
        warning_system_count: int,
        worst_critical_lag_minutes: float | None,
    ) -> None:
        """Create/clear critical telemetry lag notification with debounce."""
        if self._connection_notifier is None:
            return

        if critical_system_count > 0:
            self._telemetry_lag_critical_poll_streak += 1
            if self._telemetry_lag_critical_poll_streak >= LAG_CRITICAL_CONSECUTIVE_POLLS:
                await self._connection_notifier.async_report_telemetry_lag_critical(
                    critical_system_count=critical_system_count,
                    warning_system_count=warning_system_count,
                    worst_lag_minutes=worst_critical_lag_minutes,
                    warning_minutes=LAG_WARNING_MINUTES,
                    critical_minutes=LAG_CRITICAL_MINUTES,
                    consecutive_polls=LAG_CRITICAL_CONSECUTIVE_POLLS,
                )
            return

        self._telemetry_lag_critical_poll_streak = 0
        await self._connection_notifier.async_clear_telemetry_lag_alert()

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
        self._low_rssi_poll_streak = 0

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
        rssi_watch_threshold = int(
            self._options.get(OPT_RSSI_WATCH_THRESHOLD, DEFAULT_RSSI_WATCH_THRESHOLD)
        )
        rssi_alert_threshold = int(
            self._options.get(OPT_RSSI_ALERT_THRESHOLD, DEFAULT_RSSI_ALERT_THRESHOLD)
        )
        rssi_alert_consecutive_polls = int(
            self._options.get(
                OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
                DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
            )
        )

        system_ids = sorted(self._summary_coordinator.tracked_system_ids)
        if not system_ids:
            fetched = datetime.now(UTC)
            await self._async_report_connection_recovered()
            await self._async_clear_low_rssi_alert()
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
                empty_window_fallback_attempts=0,
                empty_window_fallback_hits=0,
                future_rows_dropped=0,
                invalid_timestamp_rows=0,
                low_rssi_module_count=0,
                watch_rssi_module_count=0,
                worst_rssi=None,
            )

        window_end = datetime.now(UTC) - timedelta(minutes=recent_cutoff_minutes)
        window_start = window_end - timedelta(minutes=backfill_minutes)

        dedupe_ignored_points = 0
        latest_seen: datetime | None = None
        fallback_attempts = 0
        fallback_hits = 0
        future_rows_dropped = 0
        invalid_timestamp_rows = 0

        for system_id in system_ids:
            system_timezone = _system_timezone_for_id(self._summary_coordinator.data.systems, system_id)
            naive_tz = _resolve_naive_timezone(
                system_timezone=system_timezone,
                hass_timezone=self.hass.config.time_zone,
            )

            for metric in METRICS:
                try:
                    parsed, fallback_attempted, fallback_hit = await self._async_fetch_metric_with_fallback(
                        system_id=system_id,
                        metric=metric,
                        window_start=window_start,
                        window_end=window_end,
                        backfill_minutes=backfill_minutes,
                        naive_tz=naive_tz,
                    )
                except TigoApiRateLimitError as err:
                    await self._async_report_connection_recovered()
                    raise UpdateFailed(
                        f"Tigo API rate limited while fetching module metric {metric} for system {system_id}",
                        retry_after=err.retry_after,
                    ) from err
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

                if fallback_attempted:
                    fallback_attempts += 1
                if fallback_hit:
                    fallback_hits += 1
                future_rows_dropped += parsed.future_rows_dropped
                invalid_timestamp_rows += parsed.invalid_timestamp_rows

                for module_id, points in parsed.rows_by_module.items():
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

        low_rssi_count, watch_rssi_count, worst_rssi = _compute_rssi_health(
            self._points_by_key,
            watch_threshold=rssi_watch_threshold,
            alert_threshold=rssi_alert_threshold,
        )
        if low_rssi_count > 0:
            self._low_rssi_poll_streak += 1
        else:
            self._low_rssi_poll_streak = 0

        fetched_at = datetime.now(UTC)
        lag_seconds = (fetched_at - latest_seen).total_seconds() if latest_seen else None
        is_stale = lag_seconds is None or lag_seconds > stale_threshold
        await self._async_report_connection_recovered()
        if low_rssi_count > 0 and self._low_rssi_poll_streak >= rssi_alert_consecutive_polls:
            await self._async_report_low_rssi_alert(
                low_count=low_rssi_count,
                watch_count=watch_rssi_count,
                worst_rssi=worst_rssi,
                alert_threshold=rssi_alert_threshold,
                watch_threshold=rssi_watch_threshold,
                consecutive_polls=rssi_alert_consecutive_polls,
            )
        elif low_rssi_count == 0:
            await self._async_clear_low_rssi_alert()

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
            empty_window_fallback_attempts=fallback_attempts,
            empty_window_fallback_hits=fallback_hits,
            future_rows_dropped=future_rows_dropped,
            invalid_timestamp_rows=invalid_timestamp_rows,
            low_rssi_module_count=low_rssi_count,
            watch_rssi_module_count=watch_rssi_count,
            worst_rssi=worst_rssi,
        )

    async def _async_fetch_metric_with_fallback(
        self,
        *,
        system_id: int,
        metric: str,
        window_start: datetime,
        window_end: datetime,
        backfill_minutes: int,
        naive_tz,
    ) -> tuple[ParsedAggregateCsv, bool, bool]:
        """Fetch one metric and retry once with wider lookback when window is empty."""
        primary_csv = await self._client.async_get_aggregate_csv(
            system_id=system_id,
            start=window_start,
            end=window_end,
            metric=metric,
        )
        primary = parse_tigo_aggregate_csv(
            primary_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )
        if _parsed_has_points(primary):
            return primary, False, False

        fallback_window_minutes = _fallback_window_minutes(backfill_minutes)
        fallback_start = window_end - timedelta(minutes=fallback_window_minutes)
        fallback_csv = await self._client.async_get_aggregate_csv(
            system_id=system_id,
            start=fallback_start,
            end=window_end,
            metric=metric,
        )
        fallback = parse_tigo_aggregate_csv(
            fallback_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )

        filtered = _filter_parsed_to_window(
            fallback,
            window_start=window_start,
            window_end=window_end,
        )
        merged = ParsedAggregateCsv(
            rows_by_module=filtered.rows_by_module,
            future_rows_dropped=primary.future_rows_dropped + fallback.future_rows_dropped,
            invalid_timestamp_rows=primary.invalid_timestamp_rows + fallback.invalid_timestamp_rows,
        )
        return merged, True, _parsed_has_points(merged)

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

    async def _async_report_low_rssi_alert(
        self,
        *,
        low_count: int,
        watch_count: int,
        worst_rssi: float | None,
        alert_threshold: int,
        watch_threshold: int,
        consecutive_polls: int,
    ) -> None:
        """Show persistent alert for sustained low RSSI values."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_report_low_rssi_alert(
            low_count=low_count,
            watch_count=watch_count,
            worst_rssi=worst_rssi,
            alert_threshold=alert_threshold,
            watch_threshold=watch_threshold,
            consecutive_polls=consecutive_polls,
        )

    async def _async_clear_low_rssi_alert(self) -> None:
        """Clear low RSSI alert notification."""
        if self._connection_notifier is None:
            return
        await self._connection_notifier.async_clear_low_rssi_alert()


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


def _compute_rssi_health(
    points_by_key: Mapping[tuple[int, str, str], ModulePoint],
    *,
    watch_threshold: int,
    alert_threshold: int,
) -> tuple[int, int, float | None]:
    """Return counts for low/watch RSSI and worst observed RSSI."""
    rssi_values = [
        point.value
        for (_, _, metric), point in points_by_key.items()
        if metric == "RSSI"
    ]
    if not rssi_values:
        return 0, 0, None

    low_count = sum(1 for value in rssi_values if value < alert_threshold)
    watch_count = sum(1 for value in rssi_values if alert_threshold <= value < watch_threshold)
    worst_rssi = min(rssi_values)
    return low_count, watch_count, worst_rssi


def _telemetry_lag_status(lag_seconds: float | None) -> str | None:
    """Return telemetry lag status label from fixed thresholds."""
    if lag_seconds is None:
        return None
    lag_minutes = lag_seconds / 60
    if lag_minutes >= LAG_CRITICAL_MINUTES:
        return "critical"
    if lag_minutes >= LAG_WARNING_MINUTES:
        return "warning"
    return "ok"


def _parsed_has_points(parsed: ParsedAggregateCsv) -> bool:
    """Return true when parsed rows contain at least one metric value."""
    return any(points for points in parsed.rows_by_module.values())


def _latest_timestamp(parsed: ParsedAggregateCsv) -> datetime | None:
    """Return latest timestamp across all parsed rows."""
    latest: datetime | None = None
    for points in parsed.rows_by_module.values():
        if not points:
            continue
        candidate = max(points, key=lambda item: item[0])[0]
        if latest is None or candidate > latest:
            latest = candidate
    return latest


def _filter_parsed_to_window(
    parsed: ParsedAggregateCsv,
    *,
    window_start: datetime,
    window_end: datetime,
) -> ParsedAggregateCsv:
    """Filter parsed data to target window, preserving parser counters."""
    filtered_rows: dict[str, list[tuple[datetime, float]]] = {}
    for module_id, points in parsed.rows_by_module.items():
        kept = [point for point in points if window_start <= point[0] <= window_end]
        if kept:
            filtered_rows[module_id] = kept
    return ParsedAggregateCsv(
        rows_by_module=filtered_rows,
        future_rows_dropped=parsed.future_rows_dropped,
        invalid_timestamp_rows=parsed.invalid_timestamp_rows,
    )


def _fallback_window_minutes(backfill_minutes: int) -> int:
    """Return widened fallback window duration in minutes."""
    return min(
        EMPTY_WINDOW_FALLBACK_MINUTES_MAX,
        max(EMPTY_WINDOW_FALLBACK_MINUTES_MIN, backfill_minutes * 2),
    )


def _resolve_naive_timezone(system_timezone: str | None, hass_timezone: str | None):
    """Resolve timezone for naive CSV bucket timestamps."""
    if system_timezone:
        try:
            return ZoneInfo(system_timezone)
        except ZoneInfoNotFoundError:
            LOGGER.debug("Invalid system timezone '%s'; falling back", system_timezone)

    if hass_timezone:
        try:
            return ZoneInfo(hass_timezone)
        except ZoneInfoNotFoundError:
            LOGGER.debug("Invalid Home Assistant timezone '%s'; falling back", hass_timezone)

    return UTC


def _system_timezone_for_id(systems: Mapping[int, SystemSnapshot], system_id: int) -> str | None:
    """Return configured timezone string for one tracked system."""
    system = systems.get(system_id)
    if system is None:
        return None
    return system.timezone
