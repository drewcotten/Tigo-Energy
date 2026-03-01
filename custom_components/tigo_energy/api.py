"""Async API client for Tigo Energy cloud API."""

from __future__ import annotations

import asyncio
import base64
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from aiohttp import ClientError, ClientResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE_URL


class TigoApiError(Exception):
    """Base class for Tigo API errors."""


class TigoApiConnectionError(TigoApiError):
    """Raised when connecting to the API fails."""


class TigoApiAuthError(TigoApiError):
    """Raised for invalid auth or expired credentials."""


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


class TigoApiClient:
    """Small async wrapper around the Tigo v3 cloud API."""

    def __init__(
        self,
        hass,
        credentials: TigoAuthCredentials,
        base_url: str = API_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self._hass = hass
        self._session = async_get_clientsession(hass)
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._token_state: TigoTokenState | None = None
        self._account_id: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def account_id(self) -> str | None:
        """Return cached account id when available."""
        return self._account_id

    async def async_login(self, force: bool = False) -> None:
        """Login and cache bearer token + account id."""
        if self._token_state is not None and not force:
            return

        async with self._login_lock:
            if self._token_state is not None and not force:
                return

            raw = f"{self._credentials.username}:{self._credentials.password}".encode()
            encoded = base64.b64encode(raw).decode()
            headers = {"Authorization": f"Basic {encoded}"}

            response = await self._safe_request("GET", "/users/login", headers=headers)
            if response.status == 401:
                raise TigoApiAuthError("Invalid username or password")
            if response.status == 429:
                raise TigoApiError("Tigo API rate limited login request")
            if response.status >= 400:
                raise TigoApiError(f"Login failed with status {response.status}")

            data = await self._read_json(response)
            user = data.get("user", data)
            token = user.get("auth") or user.get("token")
            user_id = user.get("user_id") or user.get("id")

            if not token:
                raise TigoApiAuthError("Login response did not include auth token")

            self._token_state = TigoTokenState(
                bearer_token=token,
                obtained_at=datetime.now(UTC),
            )
            if user_id is not None:
                self._account_id = str(user_id)

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
    ) -> str:
        """Fetch aggregate CSV for one metric."""
        params = {
            "system_id": system_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "level": "minute",
            "param": metric,
            "header": "id",
            "sensors": "true",
        }
        return await self._async_request_text("GET", "/data/aggregate", params=params)

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

        response = await self._safe_request(method, path, headers=headers, params=params)

        if response.status == 401 and retry_auth:
            self._token_state = None
            await self.async_login(force=True)
            return await self._async_request(method, path, params=params, retry_auth=False)

        if response.status == 401:
            raise TigoApiAuthError("Authentication failed after token refresh")
        if response.status == 429:
            raise TigoApiError("Tigo API rate limit exceeded")
        if response.status >= 400:
            raise TigoApiError(f"Request failed with status {response.status}")

        return response

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


def parse_tigo_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp string into timezone-aware UTC datetime when possible."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    text = str(value).strip()
    if not text:
        return None

    # Try ISO8601 first.
    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    # Common Tigo formats observed in community clients.
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue

    return None


def parse_tigo_aggregate_csv(csv_text: str) -> dict[str, list[tuple[datetime, float]]]:
    """Parse aggregate CSV into module_id => [(timestamp, value)]."""
    if not csv_text.strip():
        return {}

    stream = StringIO(csv_text)
    reader = csv.DictReader(stream)
    rows: dict[str, list[tuple[datetime, float]]] = {}

    for row in reader:
        # Try common timestamp headers.
        ts_raw = row.get("Datetime") or row.get("DATETIME") or row.get("datetime")
        timestamp = parse_tigo_timestamp(ts_raw)
        if timestamp is None:
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

    return rows
