"""Tests for Tigo API client."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from aioresponses import aioresponses

from custom_components.tigo_energy.api import (
    TigoApiAuthError,
    TigoApiClient,
    TigoApiRateLimitError,
    TigoAuthCredentials,
    parse_tigo_timestamp,
)

BASE = "https://api2.tigoenergy.com/api/v3"


async def test_login_success(hass):
    """Test successful login extracts token and account id."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )

        await client.async_login()

    assert client.account_id == "42"


async def test_login_falls_back_to_get_when_post_not_supported(hass):
    """Test login fallback POST -> GET for incompatible method/status."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users/login", status=404)
        mocked.get(
            f"{BASE}/users/login",
            status=200,
            payload={"data": {"auth": "token-1", "user_id": 42}},
        )

        await client.async_login()

    assert client.account_id == "42"


async def test_request_retries_login_on_401(hass):
    """Test request retries once by re-authenticating after 401."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(re.compile(rf"{BASE}/systems.*"), status=401)
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-2", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/systems.*"),
            status=200,
            payload={"systems": [{"system_id": 1001}]},
        )

        systems = await client.async_list_systems()

    assert systems == [{"system_id": 1001}]


async def test_login_invalid_auth(hass):
    """Test invalid auth error on login."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="bad"))

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users/login", status=401)

        try:
            await client.async_login()
        except TigoApiAuthError:
            pass
        else:  # pragma: no cover
            raise AssertionError("Expected TigoApiAuthError")


async def test_login_reads_top_level_and_nested_tokens(hass):
    """Token extraction should support top-level, user, and data containers."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"auth": "top-token", "id": 11},
        )
        await client.async_login(force=True)

        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"token": "user-token", "user_id": 12}},
        )
        await client.async_login(force=True)

        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"data": {"auth": "data-token", "account_id": "13"}},
        )
        await client.async_login(force=True)

    assert client.account_id == "13"


async def test_request_retries_on_429_with_retry_after(hass):
    """429 should retry honoring Retry-After and eventually succeed."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with (
        aioresponses() as mocked,
        patch("custom_components.tigo_energy.api.asyncio.sleep", AsyncMock()) as mock_sleep,
    ):
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/systems.*"),
            status=429,
            headers={"Retry-After": "1"},
        )
        mocked.get(
            re.compile(rf"{BASE}/systems.*"),
            status=200,
            payload={"systems": [{"system_id": 1001}]},
        )

        systems = await client.async_list_systems()

    assert systems == [{"system_id": 1001}]
    mock_sleep.assert_awaited()


async def test_request_raises_rate_limit_error_after_max_retries(hass):
    """Exhausted 429 retries should raise a dedicated rate-limit exception."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with (
        aioresponses() as mocked,
        patch("custom_components.tigo_energy.api.asyncio.sleep", AsyncMock()),
    ):
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        for _ in range(4):
            mocked.get(
                re.compile(rf"{BASE}/systems.*"),
                status=429,
                headers={"Retry-After": "2"},
            )

        with pytest.raises(TigoApiRateLimitError) as err:
            await client.async_list_systems()

    assert err.value.retry_after == 2.0


async def test_proactive_refresh_uses_expires(hass):
    """Expired token metadata should trigger re-login before request."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={
                "user": {
                    "auth": "token-expired",
                    "user_id": 42,
                    "expires": "2000-01-01T00:00:00+00:00",
                }
            },
        )
        await client.async_login()

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-fresh", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/systems.*"),
            status=200,
            payload={"systems": [{"system_id": 1001}]},
        )

        systems = await client.async_list_systems()

    assert systems == [{"system_id": 1001}]


def test_parse_tigo_timestamp_slash_format_uses_naive_timezone():
    """Slash-format naive CSV timestamps should use provided local timezone."""
    dt = parse_tigo_timestamp("2026/03/01 12:07:00", naive_tz=ZoneInfo("America/Denver"))

    assert dt is not None
    expected = datetime(2026, 3, 1, 19, 7, 0, tzinfo=UTC)
    assert dt == expected
