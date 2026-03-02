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
    TigoApiError,
    TigoApiRateLimitError,
    TigoAuthCredentials,
    _format_query_timestamp,
    _retry_delay_seconds,
    parse_tigo_aggregate_csv,
    parse_tigo_timestamp,
)

BASE = "https://api2.tigoenergy.com/api/v3"


async def test_login_success(hass):
    """Test successful login extracts token and account id."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )

        await client.async_login()

    assert client.account_id == "42"


async def test_login_falls_back_to_get_when_post_not_supported(hass):
    """Test login fallback from preferred to legacy login endpoints."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", status=404)
        mocked.get(f"{BASE}/user/login", status=404)
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
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(re.compile(rf"{BASE}/systems.*"), status=401)
        mocked.post(
            f"{BASE}/user/login",
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
        mocked.post(f"{BASE}/user/login", status=401)

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
            f"{BASE}/user/login",
            status=200,
            payload={"auth": "top-token", "id": 11},
        )
        await client.async_login(force=True)

        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"token": "user-token", "user_id": 12}},
        )
        await client.async_login(force=True)

        mocked.post(
            f"{BASE}/user/login",
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
            f"{BASE}/user/login",
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
            f"{BASE}/user/login",
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
            f"{BASE}/user/login",
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
            f"{BASE}/user/login",
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


async def test_combined_csv_prefers_spec_params(hass):
    """Combined fetch should first use the documented v3 query shape."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))
    client._async_request_text = AsyncMock(return_value="Datetime,combined\n")

    result = await client.async_get_combined_csv(
        system_id=1001,
        start=datetime(2026, 3, 1, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 21, 0, 0, tzinfo=UTC),
        metric="Pin",
    )

    assert result == "Datetime,combined\n"
    params = client._async_request_text.await_args_list[0].kwargs["params"]
    assert params["level"] == "minute"
    assert "param" not in params
    assert "header" not in params


async def test_combined_csv_falls_back_to_agg_alias_params(hass):
    """If level-shape fails, client retries with agg alias."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))
    client._async_request_text = AsyncMock(
        side_effect=[TigoApiError("bad request"), "Datetime,combined\n"]
    )

    result = await client.async_get_combined_csv(
        system_id=1001,
        start=datetime(2026, 3, 1, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 21, 0, 0, tzinfo=UTC),
        metric="Pin",
    )

    assert result == "Datetime,combined\n"
    assert client._async_request_text.await_count == 2
    params = client._async_request_text.await_args_list[1].kwargs["params"]
    assert "level" not in params
    assert params["agg"] == "minute"
    assert "param" not in params
    assert "header" not in params


async def test_combined_csv_falls_back_to_legacy_params(hass):
    """If spec + agg fail, client retries with legacy param/header."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))
    client._async_request_text = AsyncMock(
        side_effect=[
            TigoApiError("bad level"),
            TigoApiError("bad agg"),
            "Datetime,combined\n",
        ]
    )

    result = await client.async_get_combined_csv(
        system_id=1001,
        start=datetime(2026, 3, 1, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 21, 0, 0, tzinfo=UTC),
        metric="Pin",
    )

    assert result == "Datetime,combined\n"
    assert client._async_request_text.await_count == 3
    params = client._async_request_text.await_args_list[2].kwargs["params"]
    assert params["level"] == "minute"
    assert params["param"] == "Pin"
    assert params["header"] == "id"


async def test_get_alerts_system_normalizes_keys(hass):
    """Alerts endpoint parsing should accept lowercase and uppercase keys."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/alerts/system.*"),
            status=200,
            payload={"Alerts": [{"alert_id": 1, "title": "x"}], "_meta": {"totalCount": 1}},
        )

        alerts, meta = await client.async_get_alerts_system(1001)

    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == 1
    assert meta == {"totalCount": 1}


async def test_get_alert_types_supports_primary_key_and_caches(hass):
    """Alert types should parse under alert_types and cache results."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/alerts/types.*"),
            status=200,
            payload={"alert_types": [{"alert_type_id": 1, "unique_id": 42, "title": "pv-off"}]},
        )

        first = await client.async_get_alert_types()
        second = await client.async_get_alert_types()

    assert len(first) == 1
    assert first[0]["unique_id"] == 42
    assert second == first


async def test_get_objects_system_caches_by_system(hass):
    """Objects endpoint should cache per-system results."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/objects/system.*system_id=1001.*"),
            status=200,
            payload={"objects": [{"id": 89287797, "label": "A1"}]},
        )

        first = await client.async_get_objects_system(1001)
        second = await client.async_get_objects_system(1001)

    assert len(first) == 1
    assert first[0]["label"] == "A1"
    assert second == first


async def test_get_system_layout_parses_systems_object(hass):
    """System layout should parse systems object payload shape."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/system/layout.*"),
            status=200,
            payload={"systems": {"system_id": 1001, "inverters": []}},
        )

        layout = await client.async_get_system_layout(1001)

    assert layout["system_id"] == 1001
    assert layout["inverters"] == []


async def test_get_system_layout_parses_system_object(hass):
    """System layout should parse singular system payload shape."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/system/layout.*"),
            status=200,
            payload={"system": {"system_id": 1001, "inverters": [{"label": "Inv 1"}]}},
        )

        layout = await client.async_get_system_layout(1001)

    assert layout["system_id"] == 1001
    assert layout["inverters"][0]["label"] == "Inv 1"


async def test_get_system_full_returns_payload(hass):
    """Systems/full endpoint should return normalized dict payload."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(
            re.compile(rf"{BASE}/systems/full.*"),
            status=200,
            payload={"strings": [{"string_id": 1, "label": "String A"}], "panels": []},
        )

        payload = await client.async_get_system_full(1001)

    assert payload["strings"][0]["string_id"] == 1


async def test_aggregate_csv_uses_key_header(hass):
    """Aggregate telemetry request should request semantic key headers."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))
    client._async_request_text = AsyncMock(return_value="Datetime,A1_Pin\n")

    await client.async_get_aggregate_csv(
        system_id=1001,
        start=datetime(2026, 3, 1, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 21, 0, 0, tzinfo=UTC),
        metric="Pin",
    )

    params = client._async_request_text.await_args.kwargs["params"]
    assert params["header"] == "key"


def test_parse_aggregate_csv_normalizes_semantic_module_labels():
    """Key-header module columns should normalize to semantic labels like A1/B12."""
    parsed = parse_tigo_aggregate_csv(
        "Datetime,04C05B800ACE.panels.A1_Vin,04C05B800ACE.panels.B12_Vin\n"
        "2026/03/01 12:07:00,34.1,35.2\n",
        naive_tz=ZoneInfo("America/Denver"),
    )

    assert "A1" in parsed.rows_by_module
    assert "B12" in parsed.rows_by_module
    assert "04C05B800ACE.panels.A1_Vin" not in parsed.rows_by_module


def test_parse_tigo_timestamp_slash_format_uses_naive_timezone():
    """Slash-format naive CSV timestamps should use provided local timezone."""
    dt = parse_tigo_timestamp("2026/03/01 12:07:00", naive_tz=ZoneInfo("America/Denver"))

    assert dt is not None
    expected = datetime(2026, 3, 1, 19, 7, 0, tzinfo=UTC)
    assert dt == expected


def test_parse_tigo_timestamp_slash_millis_uses_naive_timezone():
    """Slash-format datetimes with fractional seconds should parse correctly."""
    dt = parse_tigo_timestamp("2026/03/01 12:07:00.250", naive_tz=ZoneInfo("America/Denver"))

    assert dt is not None
    expected = datetime(2026, 3, 1, 19, 7, 0, 250000, tzinfo=UTC)
    assert dt == expected


def test_retry_delay_uses_rate_limit_reset_when_retry_after_missing():
    """X-Rate-Limit-Reset should be used when Retry-After is absent."""

    class _Response:
        def __init__(self) -> None:
            self.headers = {"X-Rate-Limit-Reset": "7"}

    delay = _retry_delay_seconds(response=_Response(), attempt=0)

    assert delay == 7.0


def test_format_query_timestamp_uses_site_wall_clock_without_offset():
    """Telemetry query timestamps should normalize to site-local wall clock."""
    dt = datetime(2026, 3, 1, 21, 13, 36, tzinfo=UTC)

    formatted = _format_query_timestamp(dt, query_tz=ZoneInfo("America/Denver"))

    assert formatted == "2026-03-01T14:13:36"


def test_format_query_timestamp_keeps_offset_when_query_timezone_unset():
    """Without query timezone normalization, retain timezone offset in request string."""
    dt = datetime(2026, 3, 1, 21, 13, 36, tzinfo=UTC)

    formatted = _format_query_timestamp(dt, query_tz=None)

    assert formatted == "2026-03-01T21:13:36+00:00"
