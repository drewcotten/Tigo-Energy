"""Data coordinators for Tigo Energy integration."""

from __future__ import annotations

import logging
import re
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
    DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
    DEFAULT_MODULE_POLL_SECONDS,
    DEFAULT_NOTIFY_CONNECTION_ISSUES,
    DEFAULT_NOTIFY_LOW_RSSI,
    DEFAULT_NOTIFY_TELEMETRY_LAG,
    DEFAULT_RECENT_CUTOFF_MINUTES,
    DEFAULT_RSSI_ALERT_CONSECUTIVE_POLLS,
    DEFAULT_RSSI_ALERT_THRESHOLD,
    DEFAULT_RSSI_WATCH_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_SUMMARY_POLL_SECONDS,
    DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
    EMPTY_WINDOW_FALLBACK_MINUTES_MAX,
    EMPTY_WINDOW_FALLBACK_MINUTES_MIN,
    ENTRY_MODE_ALL_SYSTEMS,
    LAG_CRITICAL_CONSECUTIVE_POLLS,
    LAG_CRITICAL_MINUTES,
    LAG_WARNING_MINUTES,
    MAX_FUTURE_BUCKET_MINUTES,
    OPT_BACKFILL_WINDOW_MINUTES,
    OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
    OPT_ENABLE_SUNSET_ALERT_GUARD,
    OPT_MODULE_POLL_SECONDS,
    OPT_NOTIFY_ACTIVE_ALERT_SUMMARY,
    OPT_NOTIFY_CONNECTION_ISSUES,
    OPT_NOTIFY_LOW_RSSI,
    OPT_NOTIFY_PV_OFF,
    OPT_NOTIFY_STRING_SHUTDOWN,
    OPT_NOTIFY_TELEMETRY_LAG,
    OPT_RECENT_CUTOFF_MINUTES,
    OPT_RSSI_ALERT_CONSECUTIVE_POLLS,
    OPT_RSSI_ALERT_THRESHOLD,
    OPT_RSSI_WATCH_THRESHOLD,
    OPT_STALE_THRESHOLD_SECONDS,
    OPT_SUMMARY_POLL_SECONDS,
    OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
    OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
)
from .models import (
    AlertRecord,
    ArraySnapshot,
    FreshnessState,
    ModulePoint,
    ModuleSnapshot,
    SolarAlertContext,
    SourceSnapshot,
    SummarySnapshot,
    SystemAlertState,
    SystemSnapshot,
)
from .notifications import (
    CONNECTION_SOURCE_MODULES,
    CONNECTION_SOURCE_SUMMARY,
    TigoConnectionNotifier,
)

METRICS: tuple[str, ...] = ("Pin", "Vin", "Iin", "RSSI")
LOGGER = logging.getLogger(__name__)
LABEL_PATTERN = re.compile(r"^[A-Za-z]\d+$")
PV_OFF_PATTERN = re.compile(r"\bpv[- ]?off\b|\brsd\b", flags=re.IGNORECASE)
SHUTDOWN_PATTERN = re.compile(
    r"\bstring shutdown\b|\bsystem shutdown\b|\bshutdown\b",
    flags=re.IGNORECASE,
)
ARRAY_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


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
        self._notify_connection_issues = bool(
            options.get(
                OPT_NOTIFY_CONNECTION_ISSUES,
                DEFAULT_NOTIFY_CONNECTION_ISSUES,
            )
        )
        self.tracked_system_ids: set[int] = set(configured_system_ids)
        self._telemetry_lag_critical_poll_streak = 0
        self._alert_warning_system_ids: set[int] = set()
        self._alert_type_warning_logged = False

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
        enable_sunset_alert_guard = bool(
            self._options.get(
                OPT_ENABLE_SUNSET_ALERT_GUARD,
                DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
            )
        )
        sun_guard_min_elevation = float(
            self._options.get(
                OPT_SUN_GUARD_MIN_ELEVATION_DEGREES,
                DEFAULT_SUN_GUARD_MIN_ELEVATION_DEGREES,
            )
        )
        sun_guard_positive_power_grace_minutes = int(
            self._options.get(
                OPT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
                DEFAULT_SUN_GUARD_POSITIVE_POWER_GRACE_MINUTES,
            )
        )
        enable_alert_feed_notifications = bool(
            self._options.get(
                OPT_ENABLE_ALERT_FEED_NOTIFICATIONS,
                DEFAULT_ENABLE_ALERT_FEED_NOTIFICATIONS,
            )
        )
        notify_telemetry_lag = bool(
            self._options.get(
                OPT_NOTIFY_TELEMETRY_LAG,
                DEFAULT_NOTIFY_TELEMETRY_LAG,
            )
        )
        notify_pv_off = bool(
            self._options.get(
                OPT_NOTIFY_PV_OFF,
                enable_alert_feed_notifications,
            )
        )
        notify_string_shutdown = bool(
            self._options.get(
                OPT_NOTIFY_STRING_SHUTDOWN,
                enable_alert_feed_notifications,
            )
        )
        notify_active_alert_summary = bool(
            self._options.get(
                OPT_NOTIFY_ACTIVE_ALERT_SUMMARY,
                enable_alert_feed_notifications,
            )
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

        if self._configured_system_ids:
            # Explicitly configured systems (for subentries or legacy mode) always win.
            target_system_ids = set(self._configured_system_ids)
        elif self._entry_mode == ENTRY_MODE_ALL_SYSTEMS:
            target_system_ids = set(systems_from_api)
        else:
            target_system_ids = set()

        if not target_system_ids:
            await self._async_report_connection_recovered()
            raise UpdateFailed("No Tigo systems available for this entry")

        window_end = datetime.now(UTC) - timedelta(minutes=recent_cutoff_minutes)
        window_start = window_end - timedelta(minutes=backfill_minutes)
        alert_types_by_unique_id: dict[int, dict[str, Any]] = {}

        try:
            alert_types = await self._client.async_get_alert_types(language="EN")
            for item in alert_types:
                unique_id = _as_optional_int(item.get("unique_id"))
                if unique_id is None:
                    continue
                alert_types_by_unique_id[unique_id] = item
            self._alert_type_warning_logged = False
        except TigoApiError as err:
            if not self._alert_type_warning_logged:
                LOGGER.warning(
                    "Failed to load Tigo alert type catalog; falling back to alert text matching: %s",
                    err,
                )
                self._alert_type_warning_logged = True

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
                (
                    latest_non_empty_telemetry,
                    latest_positive_telemetry,
                ) = await self._async_fetch_combined_latest_timestamps(
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

            alerts_supported = True
            alerts_raw: list[dict[str, Any]] = []
            try:
                alerts_raw, _alerts_meta = await self._client.async_get_alerts_system(
                    system_id=system_id,
                    page=1,
                    per_page=50,
                )
            except TigoApiError as err:
                alerts_supported = False
                if system_id not in self._alert_warning_system_ids:
                    LOGGER.warning(
                        "Failed to fetch alerts for system %s; alert entities will show unsupported: %s",
                        system_id,
                        err,
                    )
                    self._alert_warning_system_ids.add(system_id)
            else:
                self._alert_warning_system_ids.discard(system_id)

            try:
                objects_raw = await self._client.async_get_objects_system(system_id)
            except TigoApiError as err:
                objects_raw = []
                LOGGER.debug(
                    "Unable to load objects for system %s; module labels may remain raw: %s",
                    system_id,
                    err,
                )

            layout_raw: dict[str, Any] = {}
            try:
                layout_raw = await self._client.async_get_system_layout(system_id)
            except TigoApiError as err:
                LOGGER.debug(
                    "Unable to load system layout for system %s; array grouping may be unavailable: %s",
                    system_id,
                    err,
                )

            combined = systems_from_api.get(system_id, {})
            system_timezone = _as_optional_str(details.get("timezone") or combined.get("timezone"))
            object_module_label_map = _build_module_label_map(objects_raw)
            (
                layout_module_label_map,
                arrays,
                module_array_map,
            ) = _build_layout_mappings(layout_raw)
            if not arrays:
                try:
                    system_full_raw = await self._client.async_get_system_full(system_id)
                except TigoApiError as err:
                    LOGGER.debug(
                        "Unable to load systems/full fallback for system %s; array grouping may be unavailable: %s",
                        system_id,
                        err,
                    )
                else:
                    (
                        full_module_label_map,
                        full_arrays,
                        full_module_array_map,
                    ) = _build_layout_mappings_from_system_full(system_full_raw)
                    if full_arrays:
                        layout_module_label_map = full_module_label_map
                        arrays = full_arrays
                        module_array_map = full_module_array_map
            module_label_map = dict(layout_module_label_map)
            module_label_map.update(object_module_label_map)
            for raw_module_id, semantic_label in module_label_map.items():
                array_id = module_array_map.get(raw_module_id)
                if array_id:
                    module_array_map[semantic_label] = array_id
            alert_records = [_build_alert_record(alert) for alert in alerts_raw]
            alert_state = _build_alert_state(
                alerts=alert_records,
                sources=sources_raw,
                alert_types_by_unique_id=alert_types_by_unique_id,
                alerts_supported=alerts_supported,
            )

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

            solar_alert_context = _build_solar_alert_context(
                hass=self.hass,
                fetched_at=fetched_for_system,
                latest_positive_telemetry_timestamp=latest_positive_telemetry,
                min_elevation_degrees=sun_guard_min_elevation,
                positive_power_grace_minutes=sun_guard_positive_power_grace_minutes,
            )
            telemetry_lag_status_raw = _telemetry_lag_status(telemetry_lag_seconds)
            telemetry_lag_status = _effective_telemetry_lag_status(
                raw_status=telemetry_lag_status_raw,
                enable_sunset_alert_guard=enable_sunset_alert_guard,
                solar_alert_context=solar_alert_context,
            )
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
                latest_positive_telemetry_timestamp=latest_positive_telemetry,
                heartbeat_age_seconds=heartbeat_age_seconds,
                telemetry_lag_seconds=telemetry_lag_seconds,
                telemetry_lag_status=telemetry_lag_status,
                telemetry_lag_status_raw=telemetry_lag_status_raw,
                alert_state=alert_state,
                solar_alert_context=solar_alert_context,
                system_status=_as_optional_str(details.get("status") or combined.get("status")),
                recent_alert_count=_as_optional_int(
                    details.get("recent_alert_count") or combined.get("recent_alert_count")
                ),
                has_monitored_modules=_as_optional_bool(
                    details.get("has_monitored_modules") if "has_monitored_modules" in details else combined.get("has_monitored_modules")
                ),
                module_label_map=module_label_map,
                arrays=arrays,
                module_array_map=module_array_map,
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
            enabled=notify_telemetry_lag,
        )
        await self._async_handle_alert_feed_notifications(
            systems=systems,
            pv_off_enabled=notify_pv_off,
            string_shutdown_enabled=notify_string_shutdown,
            active_alert_summary_enabled=notify_active_alert_summary,
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

    async def _async_fetch_combined_latest_timestamps(
        self,
        *,
        system_id: int,
        window_start: datetime,
        window_end: datetime,
        backfill_minutes: int,
        naive_tz,
    ) -> tuple[datetime | None, datetime | None]:
        """Fetch latest non-empty and latest-positive combined timestamps for one system."""
        primary_csv = await self._client.async_get_combined_csv(
            system_id=system_id,
            start=window_start,
            end=window_end,
            metric="Pin",
            query_tz=naive_tz,
        )
        primary = parse_tigo_aggregate_csv(
            primary_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )
        if _parsed_has_points(primary):
            return _latest_timestamp(primary), _latest_positive_timestamp(primary)

        fallback_window_minutes = _fallback_window_minutes(backfill_minutes)
        fallback_start = window_end - timedelta(minutes=fallback_window_minutes)
        fallback_csv = await self._client.async_get_combined_csv(
            system_id=system_id,
            start=fallback_start,
            end=window_end,
            metric="Pin",
            query_tz=naive_tz,
        )
        fallback = parse_tigo_aggregate_csv(
            fallback_csv,
            naive_tz=naive_tz,
            now_utc=datetime.now(UTC),
            future_skew_minutes=MAX_FUTURE_BUCKET_MINUTES,
        )
        filtered = _filter_parsed_to_window(fallback, window_start=window_start, window_end=window_end)
        return _latest_timestamp(filtered), _latest_positive_timestamp(filtered)

    async def _async_handle_telemetry_lag_notifications(
        self,
        *,
        critical_system_count: int,
        warning_system_count: int,
        worst_critical_lag_minutes: float | None,
        enabled: bool,
    ) -> None:
        """Create/clear critical telemetry lag notification with debounce."""
        if self._connection_notifier is None:
            return
        if not enabled:
            self._telemetry_lag_critical_poll_streak = 0
            await self._connection_notifier.async_clear_telemetry_lag_alert()
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

    async def _async_handle_alert_feed_notifications(
        self,
        *,
        systems: Mapping[int, SystemSnapshot],
        pv_off_enabled: bool,
        string_shutdown_enabled: bool,
        active_alert_summary_enabled: bool,
    ) -> None:
        """Create/clear alert-feed persistent notifications."""
        if self._connection_notifier is None:
            return

        if not any((pv_off_enabled, string_shutdown_enabled, active_alert_summary_enabled)):
            await self._connection_notifier.async_clear_pv_off_alert()
            await self._connection_notifier.async_clear_string_shutdown_alert()
            await self._connection_notifier.async_clear_active_alerts()
            return

        pv_off_system_names = sorted(
            system.name for system in systems.values() if system.alert_state.pv_off_active
        )
        if not pv_off_enabled:
            await self._connection_notifier.async_clear_pv_off_alert()
        elif pv_off_system_names:
            await self._connection_notifier.async_report_pv_off_active(
                system_names=pv_off_system_names,
                system_count=len(pv_off_system_names),
            )
        else:
            await self._connection_notifier.async_clear_pv_off_alert()

        shutdown_system_names = sorted(
            system.name for system in systems.values() if system.alert_state.string_shutdown_active
        )
        if not string_shutdown_enabled:
            await self._connection_notifier.async_clear_string_shutdown_alert()
        elif shutdown_system_names:
            await self._connection_notifier.async_report_string_shutdown_active(
                system_names=shutdown_system_names,
                system_count=len(shutdown_system_names),
            )
        else:
            await self._connection_notifier.async_clear_string_shutdown_alert()

        systems_with_alerts = [
            system for system in systems.values() if system.alert_state.active_count > 0
        ]
        total_active_alerts = sum(system.alert_state.active_count for system in systems_with_alerts)
        latest_alert = _latest_active_alert(
            [
                system.alert_state.latest_active_alert
                for system in systems_with_alerts
                if system.alert_state.latest_active_alert is not None
            ]
        )
        if not active_alert_summary_enabled:
            await self._connection_notifier.async_clear_active_alerts()
        elif total_active_alerts > 0:
            await self._connection_notifier.async_report_active_alerts(
                total_active_alerts=total_active_alerts,
                affected_system_count=len(systems_with_alerts),
                latest_alert_title=latest_alert.title if latest_alert else None,
                latest_alert_code=latest_alert.unique_id if latest_alert else None,
                latest_alert_time=(
                    (latest_alert.generated or latest_alert.added).isoformat()
                    if latest_alert and (latest_alert.generated or latest_alert.added)
                    else None
                ),
            )
        else:
            await self._connection_notifier.async_clear_active_alerts()

    async def _async_report_connection_failure(self) -> None:
        """Show connectivity notification when this coordinator cannot reach API."""
        if self._connection_notifier is None:
            return
        if not self._notify_connection_issues:
            return
        await self._connection_notifier.async_report_connection_failure(CONNECTION_SOURCE_SUMMARY)

    async def _async_report_connection_recovered(self) -> None:
        """Dismiss connectivity notification when this coordinator recovers."""
        if self._connection_notifier is None:
            return
        if not self._notify_connection_issues:
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
        self._notify_connection_issues = bool(
            options.get(
                OPT_NOTIFY_CONNECTION_ISSUES,
                DEFAULT_NOTIFY_CONNECTION_ISSUES,
            )
        )
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
        enable_sunset_alert_guard = bool(
            self._options.get(
                OPT_ENABLE_SUNSET_ALERT_GUARD,
                DEFAULT_ENABLE_SUNSET_ALERT_GUARD,
            )
        )
        notify_low_rssi = bool(
            self._options.get(
                OPT_NOTIFY_LOW_RSSI,
                DEFAULT_NOTIFY_LOW_RSSI,
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
            module_label_map = _system_module_label_map(self._summary_coordinator.data.systems, system_id)
            self._canonicalize_cached_points_for_system(system_id, module_label_map)

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

                for raw_module_id, points in parsed.rows_by_module.items():
                    if not points:
                        continue
                    module_id = module_label_map.get(str(raw_module_id), str(raw_module_id))
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
        low_rssi_system_ids = _low_rssi_system_ids(
            self._points_by_key,
            alert_threshold=rssi_alert_threshold,
        )
        low_rssi_guard_active = (
            not enable_sunset_alert_guard
            or any(
                _system_guard_active(self._summary_coordinator.data.systems.get(system_id))
                for system_id in low_rssi_system_ids
            )
        )

        if notify_low_rssi and low_rssi_count > 0 and low_rssi_guard_active:
            self._low_rssi_poll_streak += 1
        else:
            self._low_rssi_poll_streak = 0

        fetched_at = datetime.now(UTC)
        lag_seconds = (fetched_at - latest_seen).total_seconds() if latest_seen else None
        is_stale = lag_seconds is None or lag_seconds > stale_threshold
        await self._async_report_connection_recovered()
        if (
            notify_low_rssi
            and low_rssi_count > 0
            and low_rssi_guard_active
            and self._low_rssi_poll_streak >= rssi_alert_consecutive_polls
        ):
            await self._async_report_low_rssi_alert(
                low_count=low_rssi_count,
                watch_count=watch_rssi_count,
                worst_rssi=worst_rssi,
                alert_threshold=rssi_alert_threshold,
                watch_threshold=rssi_watch_threshold,
                consecutive_polls=rssi_alert_consecutive_polls,
            )
        elif (not notify_low_rssi) or low_rssi_count == 0 or not low_rssi_guard_active:
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

    def _canonicalize_cached_points_for_system(
        self,
        system_id: int,
        module_label_map: Mapping[str, str],
    ) -> None:
        """Remap cached module keys to semantic labels when available."""
        if not module_label_map:
            return

        remapped: dict[tuple[int, str, str], ModulePoint] = {}
        stale_keys: list[tuple[int, str, str]] = []

        for key, point in self._points_by_key.items():
            point_system_id, raw_module_id, metric = key
            if point_system_id != system_id:
                continue
            canonical_module_id = module_label_map.get(raw_module_id, raw_module_id)
            if canonical_module_id == raw_module_id:
                continue

            stale_keys.append(key)
            new_key = (point_system_id, canonical_module_id, metric)
            current = self._points_by_key.get(new_key) or remapped.get(new_key)
            if current is None or point.timestamp > current.timestamp:
                remapped[new_key] = ModulePoint(
                    system_id=point_system_id,
                    module_id=canonical_module_id,
                    metric=metric,
                    value=point.value,
                    timestamp=point.timestamp,
                )

        for key in stale_keys:
            self._points_by_key.pop(key, None)
        self._points_by_key.update(remapped)

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
            query_tz=naive_tz,
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
            query_tz=naive_tz,
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
        if not self._notify_connection_issues:
            return
        await self._connection_notifier.async_report_connection_failure(CONNECTION_SOURCE_MODULES)

    async def _async_report_connection_recovered(self) -> None:
        """Dismiss connectivity notification when this coordinator recovers."""
        if self._connection_notifier is None:
            return
        if not self._notify_connection_issues:
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


def _build_module_label_map(objects_raw: list[dict[str, Any]]) -> dict[str, str]:
    """Build raw object id => semantic module label map."""
    label_map: dict[str, str] = {}
    for obj in objects_raw:
        raw_id = obj.get("object_id") if obj.get("object_id") not in (None, "") else obj.get("id")
        label = _as_optional_str(obj.get("label"))
        if raw_id in (None, "") or not label or not LABEL_PATTERN.match(label):
            continue
        label_map[str(raw_id)] = label
    return label_map


def _build_module_label_map_from_layout(layout_raw: dict[str, Any]) -> dict[str, str]:
    """Build module label map from /system/layout nested panel structure."""
    label_map, _, _ = _build_layout_mappings(layout_raw)
    return label_map


def _build_layout_mappings(
    layout_raw: dict[str, Any],
) -> tuple[dict[str, str], dict[str, ArraySnapshot], dict[str, str]]:
    """Extract module labels, arrays, and module->array mapping from /system/layout."""
    module_label_map: dict[str, str] = {}
    arrays: dict[str, ArraySnapshot] = {}
    module_array_map: dict[str, str] = {}

    for inverter in layout_raw.get("inverters", []):
        if not isinstance(inverter, dict):
            continue
        inverter_label = _as_optional_str(inverter.get("label"))
        for mppt in inverter.get("mppts", []):
            if not isinstance(mppt, dict):
                continue
            mppt_label = _as_optional_str(mppt.get("label"))
            for string_data in mppt.get("strings", []):
                if not isinstance(string_data, dict):
                    continue

                base_array_id = _array_id_from_string(string_data)
                array_id = _unique_array_id(base_array_id, arrays)
                short_label = _as_optional_str(string_data.get("short_label"))
                string_id = _as_optional_int(string_data.get("string_id"))
                array_name = _array_name_from_string(
                    label=_as_optional_str(string_data.get("label")),
                    short_label=short_label,
                    string_id=string_id,
                )

                panel_labels: list[str] = []
                for panel in string_data.get("panels", []):
                    if not isinstance(panel, dict):
                        continue
                    label = _as_optional_str(panel.get("label"))
                    if not label or not LABEL_PATTERN.match(label):
                        continue
                    panel_labels.append(label)
                    module_array_map[label] = array_id
                    for key in ("object_id", "panel_id"):
                        raw_id = panel.get(key)
                        if raw_id in (None, ""):
                            continue
                        raw_text = str(raw_id)
                        module_label_map[raw_text] = label
                        module_array_map[raw_text] = array_id

                arrays[array_id] = ArraySnapshot(
                    array_id=array_id,
                    name=array_name,
                    short_label=short_label,
                    string_id=string_id,
                    mppt_label=mppt_label,
                    inverter_label=inverter_label,
                    panel_labels=tuple(sorted(set(panel_labels))),
                )

    return module_label_map, arrays, module_array_map


def _build_layout_mappings_from_system_full(
    systems_full_raw: dict[str, Any],
) -> tuple[dict[str, str], dict[str, ArraySnapshot], dict[str, str]]:
    """Extract module labels, arrays, and module->array mapping from /systems/full."""
    module_label_map: dict[str, str] = {}
    arrays: dict[str, ArraySnapshot] = {}
    module_array_map: dict[str, str] = {}

    if not isinstance(systems_full_raw, dict):
        return module_label_map, arrays, module_array_map

    string_to_array_id: dict[int, str] = {}
    array_panel_labels: dict[str, set[str]] = {}

    mppt_by_id = {
        mppt_id: item
        for item in systems_full_raw.get("mppts", [])
        if isinstance(item, dict)
        if (mppt_id := _as_optional_int(item.get("mppt_id"))) is not None
    }
    inverter_by_id = {
        inverter_id: item
        for item in systems_full_raw.get("inverters", [])
        if isinstance(item, dict)
        if (inverter_id := _as_optional_int(item.get("inverter_id"))) is not None
    }

    for string_data in systems_full_raw.get("strings", []):
        if not isinstance(string_data, dict):
            continue
        base_array_id = _array_id_from_string(string_data)
        array_id = _unique_array_id(base_array_id, arrays)
        string_id = _as_optional_int(string_data.get("string_id"))
        if string_id is not None:
            string_to_array_id[string_id] = array_id

        short_label = _as_optional_str(string_data.get("short_label"))
        mppt_id = _as_optional_int(string_data.get("mppt_id"))
        inverter_id = _as_optional_int(string_data.get("inverter_id"))

        mppt_label = None
        if mppt_id is not None:
            mppt = mppt_by_id.get(mppt_id)
            if mppt is not None:
                mppt_label = _as_optional_str(mppt.get("label"))
                if inverter_id is None:
                    inverter_id = _as_optional_int(mppt.get("inverter_id"))
        inverter_label = (
            _as_optional_str(inverter_by_id.get(inverter_id, {}).get("label"))
            if inverter_id is not None
            else None
        )

        arrays[array_id] = ArraySnapshot(
            array_id=array_id,
            name=_array_name_from_string(
                label=_as_optional_str(string_data.get("label")),
                short_label=short_label,
                string_id=string_id,
            ),
            short_label=short_label,
            string_id=string_id,
            mppt_label=mppt_label,
            inverter_label=inverter_label,
            panel_labels=(),
        )
        array_panel_labels[array_id] = set()

    for panel in systems_full_raw.get("panels", []):
        if not isinstance(panel, dict):
            continue
        label = _as_optional_str(panel.get("label"))
        if not label or not LABEL_PATTERN.match(label):
            continue

        string_id = _as_optional_int(panel.get("string_id"))
        array_id = string_to_array_id.get(string_id) if string_id is not None else None
        if array_id is None:
            base_array_id = f"string_{string_id}" if string_id is not None else "array_unknown"
            array_id = _unique_array_id(base_array_id, arrays)
            if string_id is not None:
                string_to_array_id[string_id] = array_id
            arrays[array_id] = ArraySnapshot(
                array_id=array_id,
                name=_array_name_from_string(label=None, short_label=None, string_id=string_id),
                short_label=None,
                string_id=string_id,
                mppt_label=None,
                inverter_label=None,
                panel_labels=(),
            )
            array_panel_labels[array_id] = set()

        module_array_map[label] = array_id
        array_panel_labels.setdefault(array_id, set()).add(label)
        for key in ("object_id", "panel_id", "id"):
            raw_id = panel.get(key)
            if raw_id in (None, ""):
                continue
            raw_text = str(raw_id)
            module_label_map[raw_text] = label
            module_array_map[raw_text] = array_id

    for array_id, array in list(arrays.items()):
        panel_labels = tuple(sorted(array_panel_labels.get(array_id, set())))
        arrays[array_id] = ArraySnapshot(
            array_id=array.array_id,
            name=array.name,
            short_label=array.short_label,
            string_id=array.string_id,
            mppt_label=array.mppt_label,
            inverter_label=array.inverter_label,
            panel_labels=panel_labels,
        )

    return module_label_map, arrays, module_array_map


def _array_id_from_string(string_data: dict[str, Any]) -> str:
    """Return stable array identifier token from a layout string node."""
    string_id = _as_optional_int(string_data.get("string_id"))
    if string_id is not None:
        return f"string_{string_id}"

    object_id = _as_optional_int(string_data.get("object_id"))
    if object_id is not None:
        return f"object_{object_id}"

    short_label = _as_optional_str(string_data.get("short_label"))
    if short_label:
        token = _array_token(short_label)
        if token:
            return f"label_{token}"

    label = _as_optional_str(string_data.get("label"))
    if label:
        token = _array_token(label)
        if token:
            return f"label_{token}"

    return "array_unknown"


def _array_name_from_string(
    *,
    label: str | None,
    short_label: str | None,
    string_id: int | None,
) -> str:
    """Return user-facing array name from layout string labels."""
    if short_label:
        return f"Array {short_label}"

    if label:
        trimmed = label.strip()
        lower = trimmed.lower()
        if lower.startswith("string "):
            suffix = trimmed[7:].strip()
            if suffix:
                return f"Array {suffix}"
        return f"Array {trimmed}"

    if string_id is not None:
        return f"Array {string_id}"

    return "Array"


def _array_token(value: str) -> str:
    """Return lowercase token used in array identifiers."""
    return ARRAY_TOKEN_PATTERN.sub("_", value.strip().lower()).strip("_")


def _unique_array_id(base: str, arrays: Mapping[str, ArraySnapshot]) -> str:
    """Return a unique array identifier token for one system snapshot."""
    if base not in arrays:
        return base

    idx = 2
    while f"{base}_{idx}" in arrays:
        idx += 1
    return f"{base}_{idx}"


def _build_alert_record(alert: dict[str, Any]) -> AlertRecord:
    """Normalize one raw alert payload into AlertRecord."""
    return AlertRecord(
        alert_id=_as_optional_int(alert.get("alert_id") or alert.get("id")),
        unique_id=_as_optional_int(alert.get("unique_id")),
        title=_as_optional_str(alert.get("title")),
        message=_as_optional_str(alert.get("message")),
        description_html=_as_optional_str(alert.get("description")),
        added=parse_tigo_timestamp(alert.get("added")),
        generated=parse_tigo_timestamp(alert.get("generated")),
        archived=bool(alert.get("archived")),
    )


def _build_alert_state(
    *,
    alerts: list[AlertRecord],
    sources: list[dict[str, Any]],
    alert_types_by_unique_id: Mapping[int, dict[str, Any]],
    alerts_supported: bool,
) -> SystemAlertState:
    """Build computed system alert and shutdown state."""
    active_alerts = [alert for alert in alerts if not alert.archived]
    latest_active_alert = _latest_active_alert(active_alerts)
    pv_off_from_control_state = any(
        _control_state_indicates_pv_off(_as_optional_str(source.get("control_state")))
        for source in sources
        if isinstance(source, dict)
    )
    pv_off_from_alerts = any(
        _alert_matches_pv_off(alert, alert_types_by_unique_id=alert_types_by_unique_id)
        for alert in active_alerts
    )
    string_shutdown_active = any(
        _alert_matches_string_shutdown(alert, alert_types_by_unique_id=alert_types_by_unique_id)
        for alert in active_alerts
    )
    return SystemAlertState(
        active_count=len(active_alerts),
        latest_active_alert=latest_active_alert,
        pv_off_active=pv_off_from_control_state or pv_off_from_alerts,
        string_shutdown_active=string_shutdown_active,
        alerts_supported=alerts_supported,
    )


def _latest_active_alert(alerts: list[AlertRecord]) -> AlertRecord | None:
    """Return most recent active alert by generated timestamp then added."""
    if not alerts:
        return None
    return max(
        alerts,
        key=lambda alert: (
            alert.generated or datetime.min.replace(tzinfo=UTC),
            alert.added or datetime.min.replace(tzinfo=UTC),
        ),
    )


def _alert_text_blob(alert: AlertRecord, alert_type: dict[str, Any] | None) -> str:
    """Build lowercase text blob used for pattern matching."""
    parts: list[str] = []
    if alert.unique_id is not None:
        parts.append(str(alert.unique_id))
    for text in (
        alert.title,
        alert.message,
        alert.description_html,
        _as_optional_str(alert_type.get("title")) if alert_type else None,
        _as_optional_str(alert_type.get("description")) if alert_type else None,
    ):
        if text:
            parts.append(text)
    return " ".join(parts).lower()


def _alert_matches_pv_off(
    alert: AlertRecord,
    *,
    alert_types_by_unique_id: Mapping[int, dict[str, Any]],
) -> bool:
    alert_type = (
        alert_types_by_unique_id.get(alert.unique_id)
        if alert.unique_id is not None
        else None
    )
    text_blob = _alert_text_blob(alert, alert_type)
    return bool(PV_OFF_PATTERN.search(text_blob))


def _alert_matches_string_shutdown(
    alert: AlertRecord,
    *,
    alert_types_by_unique_id: Mapping[int, dict[str, Any]],
) -> bool:
    alert_type = (
        alert_types_by_unique_id.get(alert.unique_id)
        if alert.unique_id is not None
        else None
    )
    text_blob = _alert_text_blob(alert, alert_type)
    return bool(SHUTDOWN_PATTERN.search(text_blob))


def _control_state_indicates_pv_off(control_state: str | None) -> bool:
    """Return true when source control_state indicates PV-off condition."""
    if not control_state:
        return False
    normalized = control_state.strip().lower()
    if normalized in {"off", "pvoff", "pv_off", "pv-off"}:
        return True
    return "off" in normalized and "pv" in normalized


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


def _as_optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
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


def _low_rssi_system_ids(
    points_by_key: Mapping[tuple[int, str, str], ModulePoint],
    *,
    alert_threshold: int,
) -> set[int]:
    """Return systems currently containing low RSSI module points."""
    systems: set[int] = set()
    for (system_id, _module_id, metric), point in points_by_key.items():
        if metric != "RSSI":
            continue
        if point.value < alert_threshold:
            systems.add(system_id)
    return systems


def _telemetry_lag_status(lag_seconds: float | None) -> str:
    """Return telemetry lag status label from fixed thresholds."""
    if lag_seconds is None:
        return "unknown"
    lag_minutes = lag_seconds / 60
    if lag_minutes >= LAG_CRITICAL_MINUTES:
        return "critical"
    if lag_minutes >= LAG_WARNING_MINUTES:
        return "warning"
    return "ok"


def _effective_telemetry_lag_status(
    *,
    raw_status: str,
    enable_sunset_alert_guard: bool,
    solar_alert_context: SolarAlertContext,
) -> str:
    """Return effective lag status after optional sunset suppression."""
    if not enable_sunset_alert_guard:
        return raw_status
    if raw_status not in {"warning", "critical"}:
        return raw_status
    if solar_alert_context.guard_active:
        return raw_status
    return "suppressed_night"


def _build_solar_alert_context(
    *,
    hass: HomeAssistant,
    fetched_at: datetime,
    latest_positive_telemetry_timestamp: datetime | None,
    min_elevation_degrees: float,
    positive_power_grace_minutes: int,
) -> SolarAlertContext:
    """Build daylight/production context used for alert gating."""
    positive_age_minutes: float | None = None
    if latest_positive_telemetry_timestamp is not None:
        positive_age_minutes = max(
            0.0,
            (fetched_at - latest_positive_telemetry_timestamp).total_seconds() / 60.0,
        )
    recent_production = (
        positive_age_minutes is not None
        and positive_age_minutes <= float(positive_power_grace_minutes)
    )

    sun_state_obj = hass.states.get("sun.sun")
    if sun_state_obj is None:
        return SolarAlertContext(
            sun_available=False,
            sun_state="unknown",
            sun_elevation=None,
            guard_active=recent_production,
            guard_reason=(
                "sun_unavailable_recent_production"
                if recent_production
                else "sun_unavailable_no_recent_production"
            ),
            latest_positive_telemetry_timestamp=latest_positive_telemetry_timestamp,
            positive_production_age_minutes=positive_age_minutes,
        )

    sun_state = sun_state_obj.state if sun_state_obj.state in {"above_horizon", "below_horizon"} else "unknown"
    sun_elevation = _as_optional_float(sun_state_obj.attributes.get("elevation"))
    sun_available = sun_state in {"above_horizon", "below_horizon"}

    if (sun_available and sun_elevation is not None and sun_elevation >= min_elevation_degrees) or (sun_available and sun_state == "above_horizon" and sun_elevation is None):
        guard_active = True
        guard_reason = "daylight"
    elif sun_available:
        guard_active = recent_production
        guard_reason = (
            "twilight_recent_production"
            if recent_production
            else "night_no_recent_production"
        )
    else:
        guard_active = recent_production
        guard_reason = (
            "sun_unavailable_recent_production"
            if recent_production
            else "sun_unavailable_no_recent_production"
        )

    return SolarAlertContext(
        sun_available=sun_available,
        sun_state=sun_state,
        sun_elevation=sun_elevation,
        guard_active=guard_active,
        guard_reason=guard_reason,
        latest_positive_telemetry_timestamp=latest_positive_telemetry_timestamp,
        positive_production_age_minutes=positive_age_minutes,
    )


def _system_guard_active(system: SystemSnapshot | Any | None) -> bool:
    """Return whether alert guard is active for one system snapshot."""
    if system is None:
        return True
    context = getattr(system, "solar_alert_context", None)
    if context is None:
        return True
    guard_active = getattr(context, "guard_active", None)
    if isinstance(guard_active, bool):
        return guard_active
    return True


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


def _latest_positive_timestamp(parsed: ParsedAggregateCsv) -> datetime | None:
    """Return latest timestamp where value is strictly positive."""
    latest: datetime | None = None
    for points in parsed.rows_by_module.values():
        for ts, value in points:
            if value <= 0:
                continue
            if latest is None or ts > latest:
                latest = ts
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


def _system_module_label_map(
    systems: Mapping[int, SystemSnapshot],
    system_id: int,
) -> Mapping[str, str]:
    """Return raw module id => semantic label map for one system."""
    system = systems.get(system_id)
    if system is None:
        return {}
    return system.module_label_map
