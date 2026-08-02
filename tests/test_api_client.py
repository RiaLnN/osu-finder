import re
import time
from unittest.mock import patch

import aiohttp
import pytest
from aioresponses import aioresponses

from osu_finder.api_client import (
    API_BASE,
    TOKEN_URL,
    OsuApiClient,
    OsuApiError,
)
from osu_finder.config import BaseFilters


@pytest.fixture
def filters():
    return BaseFilters(
        mode="osu",
        status="ranked",
        keywords="camellia",
        genre=None,
        language=None,
        sort="ranked_desc",
    )


@pytest.fixture
def client():
    return OsuApiClient(
        client_id="123",
        client_secret="secret",
        request_delay=0,
    )


# -------------------------------------------------------
# OAuth
# -------------------------------------------------------


@pytest.mark.asyncio
async def test_get_oauth_token(client):
    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "abc123",
                "expires_in": 3600,
            },
        )

        async with client:
            await client._ensure_token()
            assert client._access_token == "abc123"


@pytest.mark.asyncio
async def test_token_is_reused(client):
    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "abc123",
                "expires_in": 3600,
            },
        )

        async with client:
            await client._ensure_token()
            await client._ensure_token()
            assert len(mocked.requests) == 1


@pytest.mark.asyncio
async def test_expired_token_is_refreshed(client):
    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "old",
                "expires_in": 3600,
            },
        )
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "new",
                "expires_in": 3600,
            },
        )

        async with client:
            await client._ensure_token()
            client._token_expires_at = time.monotonic() - 1
            await client._ensure_token()
            assert client._access_token == "new"


# -------------------------------------------------------
# HTTP errors / retry
# -------------------------------------------------------


@pytest.mark.asyncio
async def test_request_refreshes_token_after_401(client):
    url = f"{API_BASE}/test"

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token1",
                "expires_in": 3600,
            },
        )
        mocked.get(
            url,
            status=401,
        )
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token2",
                "expires_in": 3600,
            },
        )
        mocked.get(
            url,
            payload={
                "ok": True,
            },
        )

        async with client:
            result = await client._request("GET", url)
            assert result == {"ok": True}


@pytest.mark.asyncio
async def test_request_retries_on_429(client):
    url = f"{API_BASE}/test"

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            url,
            status=429,
            headers={"Retry-After": "0"},
        )
        mocked.get(
            url,
            payload={"success": True},
        )

        async with client:
            result = await client._request("GET", url)
            assert result["success"] is True


@pytest.mark.asyncio
async def test_request_fails_after_max_retries(client):
    url = f"{API_BASE}/test"

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )

        for _ in range(5):
            mocked.get(
                url,
                status=429,
                headers={"Retry-After": "0"},
            )

        async with client:
            with pytest.raises(OsuApiError):
                await client._request("GET", url)


# -------------------------------------------------------
# Search parameters
# -------------------------------------------------------


def test_build_search_params(filters):
    params = OsuApiClient._build_search_params(filters, None)
    assert params == {
        "m": 0,
        "sort": "ranked_desc",
        "s": "ranked",
        "q": "camellia",
    }


def test_build_search_params_with_cursor(filters):
    params = OsuApiClient._build_search_params(filters, "cursor123")
    assert params["cursor_string"] == "cursor123"


def test_build_search_params_without_optional_fields():
    filters = BaseFilters(
        mode="mania",
        status="any",
        keywords="",
        genre=None,
        language=None,
        sort="difficulty_desc",
    )

    params = OsuApiClient._build_search_params(filters, None)

    assert params == {
        "m": 3,
        "sort": "difficulty_desc",
    }


# -------------------------------------------------------
# Beatmap search
# -------------------------------------------------------


@pytest.mark.asyncio
async def test_search_beatmapsets(client, filters):
    url = f"{API_BASE}/beatmapsets/search"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            pattern,
            payload={
                "beatmapsets": [{"id": 123}]
            },
        )

        async with client:
            result = await client.search_beatmapsets(filters)
            assert result["beatmapsets"][0]["id"] == 123


@pytest.mark.asyncio
async def test_iter_beatmapsets_pagination(client, filters):
    url = f"{API_BASE}/beatmapsets/search"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )

        # Вызов 1 (возвращает курсор "next")
        mocked.get(
            pattern,
            payload={
                "beatmapsets": [{"id": 1}],
                "cursor_string": "next",
            },
        )

        # Вызов 2 (курсор закончился)
        mocked.get(
            pattern,
            payload={
                "beatmapsets": [{"id": 2}]
            },
        )

        async with client:
            result = [
                x async for x in client.iter_beatmapsets(
                    filters,
                    max_pages=2,
                )
            ]

            assert result == [{"id": 1}, {"id": 2}]


# -------------------------------------------------------
# User API
# -------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_id_by_username(client):
    url = f"{API_BASE}/users/player"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            pattern,
            payload={"id": 999},
        )

        async with client:
            result = await client.get_user_id_by_username("player")
            assert result == 999


@pytest.mark.asyncio
async def test_get_user_best_scores(client):
    url = f"{API_BASE}/users/999/scores/best"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            pattern,
            payload=[{"pp": 300}],
        )

        async with client:
            result = await client.get_user_best_scores(999)
            assert result[0]["pp"] == 300


@pytest.mark.asyncio
async def test_get_user_best_scores_invalid_response(client):
    url = f"{API_BASE}/users/999/scores/best"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            pattern,
            payload={"error": "wrong"},
        )

        async with client:
            with pytest.raises(OsuApiError):
                await client.get_user_best_scores(999)


# -------------------------------------------------------
# API error handling
# -------------------------------------------------------


@pytest.mark.asyncio
async def test_api_returns_error(client):
    url = f"{API_BASE}/bad"
    pattern = re.compile(rf"^{re.escape(url)}.*$")

    with aioresponses() as mocked:
        mocked.post(
            TOKEN_URL,
            payload={
                "access_token": "token",
                "expires_in": 3600,
            },
        )
        mocked.get(
            pattern,
            status=500,
            payload={"message": "server error"},
        )

        async with client:
            with pytest.raises(OsuApiError) as exc:
                await client._request("GET", url)

            assert exc.value.status == 500