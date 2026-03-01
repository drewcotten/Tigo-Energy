"""Tests for Tigo API client."""

from __future__ import annotations

import re

from aioresponses import aioresponses

from custom_components.tigo_energy.api import TigoApiAuthError, TigoApiClient, TigoAuthCredentials

BASE = "https://api2.tigoenergy.com/api/v3"


async def test_login_success(hass):
    """Test successful login extracts token and account id."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.get(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )

        await client.async_login()

    assert client.account_id == "42"


async def test_request_retries_login_on_401(hass):
    """Test request retries once by re-authenticating after 401."""
    client = TigoApiClient(hass, TigoAuthCredentials(username="u", password="p"))

    with aioresponses() as mocked:
        mocked.get(
            f"{BASE}/users/login",
            status=200,
            payload={"user": {"auth": "token-1", "user_id": 42}},
        )
        mocked.get(re.compile(rf"{BASE}/systems.*"), status=401)
        mocked.get(
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
        mocked.get(f"{BASE}/users/login", status=401)

        try:
            await client.async_login()
        except TigoApiAuthError:
            pass
        else:  # pragma: no cover
            raise AssertionError("Expected TigoApiAuthError")
