"""Async API client for Tigo Energy cloud API."""

from __future__ import annotations

import asyncio
import base64
import csv
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from io import StringIO
from typing import Any

from aiohttp import ClientError, ClientResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    DEFAULT_429_BACKOFF_SECONDS,
    DEFAULT_TOKEN_REFRESH_LEAD_SECONDS,
    MAX_429_BACKOFF_SECONDS,
    MAX_429_RETRIES,
    MAX_FUTURE_BUCKET_MINUTES,
)

LOGIN_FALLBACK_STATUSES = frozenset({404, 405, 415})


class TigoApiError(Exception):
    """Base class for Tigo API errors."""


class TigoApiConnectionError(TigoApiError):
    """Raised when connecting to the API fails."""


class TigoApiAuthError(TigoApiError):
    """Raised for invalid auth or expired credentials."""


class TigoApiRateLimitError(TigoApiError):
    """Raised when API rate-limit retries are exhausted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(slots=True)
class TigoAuthCredentials:
    """Credential payload for login."""

    username: str
    password: str


@dataclass(slots=True)
class TigoTokenState:
    """Token state returned by login."""

    bearer_token: str
    obtained_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class ParsedAggregateCsv:
    """Parsed aggregate/combined CSV payload and cleanup counters."""

    rows_by_module: dict[str, list[tuple[datetime, float]]]
    future_rows_dropped: int = 0
    invalid_timestamp_rows: int = 0


class TigoApiClient:
    """Small async wrapper around the Tigo v3 cloud API."""

    def __init__(
        self,
        hass,
        credentials: TigoAuthCredentials,
        base_url: str = API_BASE_URL,
        timeout_seconds: int = 30,
        token_refresh_lead_seconds: int = DEFAULT_TOKEN_REFRESH_LEAD_SECONDS,
    ) -> None:
        self._hass = hass
        self._session = async_get_clientsession(hass)
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._token_refresh_lead_seconds = token_refresh_lead_seconds
        self._token_state: TigoTokenState | None = None
        self._account_id: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def account_id(self) -> str | None:
        """Return cached account id when available."""
        return self._account_id

    async def async_login(self, force: bool = False) -> None:
        """Login and cache bearer token + account id."""
        if self._token_state is not None and not force and not self._token_needs_refresh():
            return

        async with self._login_lock:
            if self._token_state is not None and not force and not self._token_needs_refresh():
                return

            raw = f"{self._credentials.username}:{self._credentials.password}".encode()
            encoded = base64.b64encode(raw).decode()
            headers = {"Authorization": f"Basic {encoded}"}

            response = await self._async_login_with_fallback(headers=headers)

            if response.status == 401:
                raise TigoApiAuthError("Invalid username or password")
            if response.status >= 400:
                raise TigoApiError(f"Login failed with status {response.status}")

            data = await self._read_json(response)
            token, user_id, expires_at = _extract_login_fields(data)
            if not token:
                raise TigoApiAuthError("Login response did not include auth token")

            self._token_state = TigoTokenState(
                bearer_token=token,
                obtained_at=datetime.now(UTC),
                expires_at=expires_at,
            )
            if user_id is not None:
                self._account_id = str(user_id)

    async def _async_login_with_fallback(self, *, headers: dict[str, str]) -> ClientResponse:
        """Attempt login using preferred and legacy endpoint variants.

        Preferred v3 flow is POST /user/login. Some environments have accepted
        /users/login historically, so keep that as compatibility fallback.
        """
        attempts: tuple[tuple[str, str], ...] = (
            ("POST", "/user/login"),
            ("GET", "/user/login"),
            ("POST", "/users/login"),
            ("GET", "/users/login"),
        )
        response: ClientResponse | None = None
        for idx, (method, path) in enumerate(attempts):
            response = await self._async_request_with_429_retry(method, path, headers=headers)
            if response.status not in LOGIN_FALLBACK_STATUSES:
                return response
            if idx == len(attempts) - 1:
                return response
        return response

    async def async_list_systems(self) -> list[dict[str, Any]]:
        """List systems accessible by the account."""
        data = await self._async_request_json("GET", "/systems", params={"page": 1, "limit": 100})
        systems = data.get("systems", [])
        if not isinstance(systems, list):
            return []
        return systems

    async def async_get_system(self, system_id: int) -> dict[str, Any]:
        """Get details for one system."""
        data = await self._async_request_json("GET", "/systems/view", params={"id": system_id})
        return data.get("system", data)

    async def async_get_summary(self, system_id: int) -> dict[str, Any]:
        """Get summary metrics for one system."""
        data = await self._async_request_json("GET", "/data/summary", params={"system_id": system_id})
        return data.get("summary", data)

    async def async_get_sources(self, system_id: int) -> list[dict[str, Any]]:
        """Get sources for one system."""
        data = await self._async_request_json(
            "GET",
            "/sources/system",
            params={"system_id": system_id},
        )
        sources = data.get("sources", [])
        if not isinstance(sources, list):
            return []
        return sources

    async def async_get_aggregate_csv(
        self,
        system_id: int,
        start: datetime,
        end: datetime,
        metric: str,
        query_tz: tzinfo | None = None,
    ) -> str:
        """Fetch aggregate CSV for one metric."""
        params = {
            "system_id": system_id,
            "start": _format_query_timestamp(start, query_tz=query_tz),
            "end": _format_query_timestamp(end, query_tz=query_tz),
            "level": "minute",
            "param": metric,
            "header": "id",
            "sensors": "true",
        }
        return await self._async_request_text("GET", "/data/aggregate", params=params)

    async def async_get_combined_csv(
        self,
        system_id: int,
        start: datetime,
        end: datetime,
        metric: str | None = None,
        query_tz: tzinfo | None = None,
    ) -> str:
        """Fetch combined CSV for one system window.

        Uses documented v3 params first (`level`), then retries with `agg`
        alias shape, then legacy `param/header` variants when metric is
        provided.
        """
        params_level = {
            "system_id": system_id,
            "start": _format_query_timestamp(start, query_tz=query_tz),
            "end": _format_query_timestamp(end, query_tz=query_tz),
            "level": "minute",
        }
        params_agg = {
            "system_id": system_id,
            "start": _format_query_timestamp(start, query_tz=query_tz),
            "end": _format_query_timestamp(end, query_tz=query_tz),
            "agg": "minute",
        }
        attempts: list[dict[str, Any]] = [params_level, params_agg]
        if metric not in (None, ""):
            attempts.append({**params_level, "param": metric, "header": "id"})
            attempts.append({**params_agg, "param": metric, "header": "id"})

        last_error: TigoApiError | None = None
        for idx, params in enumerate(attempts):
            try:
                return await self._async_request_text("GET", "/data/combined", params=params)
            except (TigoApiAuthError, TigoApiConnectionError, TigoApiRateLimitError):
                raise
            except TigoApiError as err:
                last_error = err
                if idx == len(attempts) - 1:
                    raise

        raise last_error or TigoApiError("Combined request failed")

    async def _async_request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        response = await self._async_request(method, path, params=params, retry_auth=retry_auth)
        data = await self._read_json(response)
        if not isinstance(data, dict):
            raise TigoApiError("Unexpected non-dict JSON response")
        return data

    async def _async_request_text(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> str:
        response = await self._async_request(method, path, params=params, retry_auth=retry_auth)
        return await response.text()

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool,
    ) -> ClientResponse:
        await self.async_login()
        headers = {"Authorization": f"Bearer {self._token_state.bearer_token}"}

        response = await self._async_request_with_429_retry(
            method,
            path,
            headers=headers,
            params=params,
        )

        if response.status == 401 and retry_auth:
            self._token_state = None
            await self.async_login(force=True)
            return await self._async_request(method, path, params=params, retry_auth=False)

        if response.status == 401:
            raise TigoApiAuthError("Authentication failed after token refresh")
        if response.status == 429:
            raise TigoApiRateLimitError("Tigo API rate limit exceeded")
        if response.status >= 400:
            raise TigoApiError(f"Request failed with status {response.status}")

        return response

    async def _async_request_with_429_retry(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> ClientResponse:
        """Request with bounded retry handling for 429 responses."""
        attempt = 0
        while attempt <= MAX_429_RETRIES:
            response = await self._safe_request(method, path, headers=headers, params=params)
            if response.status != 429:
                return response

            delay = _retry_delay_seconds(response=response, attempt=attempt)
            if attempt == MAX_429_RETRIES:
                raise TigoApiRateLimitError(
                    "Tigo API rate limit exceeded after retries",
                    retry_after=delay,
                )
            await asyncio.sleep(delay)
            attempt += 1

        raise TigoApiRateLimitError("Tigo API rate limit exceeded")

    def _token_needs_refresh(self) -> bool:
        """Return true when cached token is near known expiration."""
        if self._token_state is None:
            return True
        if self._token_state.expires_at is None:
            return False
        refresh_at = self._token_state.expires_at - timedelta(
            seconds=self._token_refresh_lead_seconds
        )
        return datetime.now(UTC) >= refresh_at

    async def _safe_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> ClientResponse:
        url = f"{self._base_url}{path}"
        try:
            return await self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=self._timeout_seconds,
            )
        except (TimeoutError, ClientError) as err:
            raise TigoApiConnectionError("Failed to communicate with Tigo API") from err

    async def _read_json(self, response: ClientResponse) -> dict[str, Any]:
        try:
            return await response.json(content_type=None)
        except ValueError as err:
            raise TigoApiError("Invalid JSON response from Tigo API") from err


def parse_tigo_timestamp(
    value: Any,
    *,
    naive_tz: tzinfo | None = UTC,
) -> datetime | None:
    """Parse a timestamp string into timezone-aware UTC datetime when possible."""
    tz_for_naive = naive_tz or UTC

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz_for_naive).astimezone(UTC)
        return value.astimezone(UTC)

    text = str(value).strip()
    if not text:
        return None

    # Try ISO8601 first.
    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz_for_naive).astimezone(UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    # Common Tigo formats observed in community clients.
    formats = (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%m/%d/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=tz_for_naive).astimezone(UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue

    return None


def _format_query_timestamp(value: datetime, *, query_tz: tzinfo | None) -> str:
    """Format request timestamp for telemetry query params.

    When query_tz is provided, convert to site-local wall-clock time and
    emit an offset-free ISO string because Tigo aggregate/combined windowing
    in some environments behaves as local bucket time.
    """
    if query_tz is None:
        return value.replace(microsecond=0).isoformat(timespec="seconds")

    localized = value.astimezone(query_tz)
    return localized.replace(tzinfo=None, microsecond=0).isoformat(timespec="seconds")


def parse_tigo_aggregate_csv(
    csv_text: str,
    *,
    naive_tz: tzinfo | None = UTC,
    now_utc: datetime | None = None,
    future_skew_minutes: int = MAX_FUTURE_BUCKET_MINUTES,
) -> ParsedAggregateCsv:
    """Parse aggregate CSV into module_id => [(timestamp, value)] with cleanup counters."""
    if not csv_text.strip():
        return ParsedAggregateCsv(rows_by_module={})

    cutoff_now = now_utc or datetime.now(UTC)
    max_future = cutoff_now + timedelta(minutes=future_skew_minutes)

    stream = StringIO(csv_text)
    reader = csv.DictReader(stream)
    rows: dict[str, list[tuple[datetime, float]]] = {}
    future_rows_dropped = 0
    invalid_timestamp_rows = 0

    for row in reader:
        ts_raw = row.get("Datetime") or row.get("DATETIME") or row.get("datetime")
        timestamp = parse_tigo_timestamp(ts_raw, naive_tz=naive_tz)
        if timestamp is None:
            invalid_timestamp_rows += 1
            continue
        if timestamp > max_future:
            future_rows_dropped += 1
            continue

        for column, raw_value in row.items():
            if column is None:
                continue
            col = column.strip()
            if col.lower() in {"datetime", "date", "time", "ts", "timestamp"}:
                continue
            if raw_value in (None, ""):
                continue
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue

            rows.setdefault(col, []).append((timestamp, numeric))

    return ParsedAggregateCsv(
        rows_by_module=rows,
        future_rows_dropped=future_rows_dropped,
        invalid_timestamp_rows=invalid_timestamp_rows,
    )


def _extract_login_fields(
    payload: dict[str, Any],
) -> tuple[str | None, str | int | None, datetime | None]:
    """Extract token/account/expires from variable login payload shapes."""
    containers: list[dict[str, Any]] = [payload]
    user = payload.get("user")
    if isinstance(user, dict):
        containers.append(user)
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)

    token: str | None = None
    user_id: str | int | None = None
    expires_at: datetime | None = None

    for container in containers:
        candidate_token = container.get("auth") or container.get("token")
        if token is None and candidate_token not in (None, ""):
            token = str(candidate_token)

        candidate_id = (
            container.get("user_id")
            or container.get("id")
            or container.get("account_id")
        )
        if user_id is None and candidate_id not in (None, ""):
            user_id = candidate_id

        candidate_expires = container.get("expires") or container.get("expires_at")
        if expires_at is None and candidate_expires not in (None, ""):
            expires_at = parse_tigo_timestamp(candidate_expires)

    return token, user_id, expires_at


def _retry_delay_seconds(response: ClientResponse, attempt: int) -> float:
    """Compute delay for 429 retries using Retry-After when possible."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        retry_after = retry_after.strip()
        if retry_after.isdigit():
            return max(0.0, float(retry_after))
        try:
            parsed = parsedate_to_datetime(retry_after)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError):
            pass

    limit_reset = response.headers.get("X-Rate-Limit-Reset")
    if limit_reset:
        try:
            return max(0.0, float(limit_reset.strip()))
        except ValueError:
            pass

    base = min(DEFAULT_429_BACKOFF_SECONDS * (2**attempt), MAX_429_BACKOFF_SECONDS)
    return float(base) + random.uniform(0.0, 1.0)
