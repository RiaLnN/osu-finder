"""
OsuApiClient — async client for the official osu! API v2.

Auth: OAuth2 Client Credentials Grant (no user login needed for public search).
https://osu.ppy.sh/docs/index.html#client-credentials-grant

`/beatmapsets/search` is officially undocumented beyond `cursor_string` — the
osu! docs literally mark it "TODO: documentation". The remaining params (q, s,
m, sort, g, l) below are inferred from the web client's behavior and confirmed
against third-party wrappers (aiosu, osu-api-v2-js). If osu! changes them,
only `_build_search_params` needs updating.

Pagination note: `/beatmapsets/search` uses a cursor, not an offset — page N+1
can only be requested once you have page N's `cursor_string`, so this endpoint
is inherently sequential and cannot be parallelized without re-fetching pages
you've already seen. `iter_beatmapsets` below is therefore a plain sequential
generator; don't try to "speed it up" with concurrent cursor walks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import aiohttp

from .config import BaseFilters

logger = logging.getLogger("osu_finder.api_client")

TOKEN_URL = "https://osu.ppy.sh/oauth/token"
API_BASE = "https://osu.ppy.sh/api/v2"

_MODE_MAP = {"osu": 0, "taiko": 1, "fruits": 2, "mania": 3}
_STATUS_MAP = {
    "ranked": "ranked",
    "qualified": "qualified",
    "loved": "loved",
    "pending": "pending",
    "graveyard": "graveyard",
}


class OsuApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"osu! API returned {status}: {message}")


class OsuApiClient:
    """OAuth2 token handling + rate limit (429) retries are transparent to callers."""

    def __init__(self, client_id: str, client_secret: str, request_delay: float = 1.0):
        self._client_id = client_id
        self._client_secret = client_secret
        self._request_delay = request_delay

        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def __aenter__(self) -> "OsuApiClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_exc_info) -> None:
        if self._session is not None:
            await self._session.close()

    # ------------------------------------------------------------------ #
    #  OAuth2
    # ------------------------------------------------------------------ #

    async def _ensure_token(self) -> None:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return

        assert self._session is not None
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
            "scope": "public",
        }
        async with self._session.post(TOKEN_URL, data=payload) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                raise OsuApiError(resp.status, f"failed to obtain access token: {body}")

        self._access_token = body["access_token"]
        # 60s safety buffer so we don't get a 401 right as the token expires
        self._token_expires_at = time.monotonic() + body["expires_in"] - 60
        logger.debug("OAuth2 token obtained, valid for %d sec.", body["expires_in"])

    # ------------------------------------------------------------------ #
    #  Requests
    # ------------------------------------------------------------------ #

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        assert self._session is not None

        for attempt in range(5):
            await self._ensure_token()
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            }
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(
                        "Rate limited (429), waiting %.1fs (attempt %d/5)", retry_after, attempt + 1
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status == 401:
                    logger.warning("401 from osu! API, refreshing token and retrying.")
                    self._access_token = None
                    continue

                body = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise OsuApiError(resp.status, str(body))
                return body

        raise OsuApiError(429, "exceeded max retries due to rate limiting")

    # ------------------------------------------------------------------ #
    #  Beatmap search
    # ------------------------------------------------------------------ #

    async def search_beatmapsets(
        self, base_filters: BaseFilters, cursor_string: Optional[str] = None
    ) -> dict[str, Any]:
        params = self._build_search_params(base_filters, cursor_string)
        await asyncio.sleep(self._request_delay)
        return await self._request("GET", f"{API_BASE}/beatmapsets/search", params=params)

    @staticmethod
    def _build_search_params(
        base_filters: BaseFilters, cursor_string: Optional[str]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "m": _MODE_MAP[base_filters.mode],
            "sort": base_filters.sort,
        }
        if base_filters.status != "any":
            params["s"] = _STATUS_MAP[base_filters.status]
        if base_filters.keywords:
            params["q"] = base_filters.keywords
        if base_filters.genre is not None:
            params["g"] = base_filters.genre
        if base_filters.language is not None:
            params["l"] = base_filters.language
        if cursor_string:
            params["cursor_string"] = cursor_string
        return params

    async def iter_beatmapsets(self, base_filters: BaseFilters, max_pages: int = 50):
        """Yields one beatmapset at a time, walking cursor_string pagination."""
        cursor: Optional[str] = None
        for page in range(max_pages):
            data = await self.search_beatmapsets(base_filters, cursor)
            beatmapsets = data.get("beatmapsets", [])
            logger.info("Search page %d: %d map(s)", page + 1, len(beatmapsets))
            if not beatmapsets:
                return
            for bset in beatmapsets:
                yield bset
            cursor = data.get("cursor_string")
            if not cursor:
                return

    # ------------------------------------------------------------------ #
    #  User profile (for `osu-finder -u <username>`)
    # ------------------------------------------------------------------ #

    async def get_user_id_by_username(self, username: str) -> int:
        await asyncio.sleep(self._request_delay)
        user_data = await self._request(
            "GET", f"{API_BASE}/users/{username}", params={"key": "username"}
        )
        return user_data["id"]

    async def get_user_best_scores(
        self, user_id: int, mode: str = "osu", limit: int = 25
    ) -> list[dict[str, Any]]:
        """GET /users/{user}/scores/best — `user_id` must be numeric."""
        await asyncio.sleep(self._request_delay)
        params = {"mode": mode, "limit": min(max(limit, 1), 100), "legacy_only": 0}
        result = await self._request("GET", f"{API_BASE}/users/{user_id}/scores/best", params=params)
        if not isinstance(result, list):
            raise OsuApiError(500, f"expected a list of scores, got {type(result)}")
        return result