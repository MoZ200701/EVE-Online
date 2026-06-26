"""Async ESI HTTP client.

The response cache is intentionally in-memory for M2. Persistent caching is
deferred until ingestion/storage milestones need it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from evemarket.config import Config

LOGGER = logging.getLogger(__name__)

ESI_BASE_URL = "https://esi.evetech.net"
ERROR_LIMIT_THRESHOLD = 5
MAX_RETRIES = 3
MAX_CONCURRENCY = 8
BACKOFF_BASE_SECONDS = 0.5

Params = Mapping[str, Any] | None
SleepCallable = Callable[[float], Awaitable[None]]
NowCallable = Callable[[], datetime]


class ESIError(RuntimeError):
    """Raised when ESI returns a non-retryable error."""


@dataclass(frozen=True)
class ESIResponse:
    """Parsed ESI response plus cache and error-budget metadata."""

    data: Any
    expires: datetime
    etag: str | None
    pages: int | None
    error_limit_remain: int | None
    error_limit_reset: int | None


@dataclass
class _CacheEntry:
    payload: Any
    expires: datetime
    etag: str | None
    pages: int | None
    error_limit_remain: int | None
    error_limit_reset: int | None


class ESIClient:
    """Small async ESI client with cache-timer and error-budget handling."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        user_agent: str | None = None,
        base_url: str = ESI_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallable = asyncio.sleep,
        now: NowCallable | None = None,
        error_limit_threshold: int = ERROR_LIMIT_THRESHOLD,
        max_retries: int = MAX_RETRIES,
        max_concurrency: int = MAX_CONCURRENCY,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
    ) -> None:
        if config is not None and user_agent is None:
            user_agent = config.user_agent

        self.user_agent = user_agent or "eve-market-tool/0.1 (contact: REPLACE_ME)"
        if "REPLACE_ME" in self.user_agent:
            LOGGER.warning(
                "ESI User-Agent still contains REPLACE_ME; set a real contact "
                "before live ESI requests."
            )

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": self.user_agent},
            http2=True,
            follow_redirects=True,
            transport=transport,
        )
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._error_limit_threshold = error_limit_threshold
        self._max_retries = max_retries
        self._max_concurrency = max_concurrency
        self._backoff_base_seconds = backoff_base_seconds
        self._error_limit_remain: int | None = None
        self._error_limit_reset: int | None = None

    async def __aenter__(self) -> ESIClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()

    async def get(self, path: str, params: Params = None) -> ESIResponse:
        """GET one ESI resource, honoring ETag/Expires and error budget."""

        key = _cache_key(path, params)
        cached = self._cache.get(key)
        now = _ensure_utc(self._now())

        if cached is not None and now < cached.expires:
            return _response_from_cache(cached)

        headers = {}
        if cached is not None and cached.etag:
            headers["If-None-Match"] = cached.etag

        response = await self._request_with_retries(path, params, headers)
        metadata = self._parse_metadata(response)

        if response.status_code == httpx.codes.NOT_MODIFIED:
            if cached is None:
                raise ESIError("ESI returned 304 but no cached payload exists.")

            cached.expires = metadata.expires
            cached.etag = metadata.etag or cached.etag
            cached.pages = metadata.pages if metadata.pages is not None else cached.pages
            cached.error_limit_remain = metadata.error_limit_remain
            cached.error_limit_reset = metadata.error_limit_reset
            return _response_from_cache(cached)

        payload = response.json()
        entry = _CacheEntry(
            payload=payload,
            expires=metadata.expires,
            etag=metadata.etag,
            pages=metadata.pages,
            error_limit_remain=metadata.error_limit_remain,
            error_limit_reset=metadata.error_limit_reset,
        )
        self._cache[key] = entry
        return _response_from_cache(entry)

    async def get_paginated(self, path: str, params: Params = None) -> list[dict]:
        """Fetch all pages for a paginated ESI resource in page order."""

        first = await self.get(path, params)
        pages = first.pages or 1
        if pages <= 1:
            return list(first.data)

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def fetch_page(page: int) -> tuple[int, list[dict]]:
            page_params = dict(params or {})
            page_params["page"] = page
            async with semaphore:
                response = await self.get(path, page_params)
            return page, list(response.data)

        results = await asyncio.gather(
            *(fetch_page(page) for page in range(2, pages + 1))
        )
        ordered_pages = [list(first.data)]
        ordered_pages.extend(data for _, data in sorted(results, key=lambda item: item[0]))
        return [item for page_data in ordered_pages for item in page_data]

    async def _request_with_retries(
        self,
        path: str,
        params: Params,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            await self._respect_error_budget()
            try:
                response = await self._client.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise ESIError(f"ESI transport error after retries: {exc}") from exc
                await self._sleep(self._backoff_seconds(attempt))
                continue

            self._update_error_budget(response)

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                if attempt >= self._max_retries:
                    raise ESIError("ESI error budget exhausted after retries.")
                await self._sleep(float(self._error_limit_reset or 1))
                continue

            if response.status_code >= 500:
                if attempt >= self._max_retries:
                    raise ESIError(
                        f"ESI server error after retries: HTTP {response.status_code}"
                    )
                await self._sleep(self._backoff_seconds(attempt))
                continue

            if response.status_code >= 400 and response.status_code != httpx.codes.NOT_MODIFIED:
                raise ESIError(f"ESI request failed: HTTP {response.status_code}")

            return response

        raise ESIError("ESI request failed after retries.")

    async def _respect_error_budget(self) -> None:
        if (
            self._error_limit_remain is not None
            and self._error_limit_remain <= self._error_limit_threshold
        ):
            await self._sleep(float(self._error_limit_reset or 1))
            self._error_limit_remain = None
            self._error_limit_reset = None

    def _backoff_seconds(self, attempt: int) -> float:
        return self._backoff_base_seconds * (2**attempt)

    def _parse_metadata(self, response: httpx.Response) -> ESIResponse:
        return ESIResponse(
            data=None,
            expires=_parse_expires(response.headers.get("Expires"), self._now()),
            etag=response.headers.get("ETag"),
            pages=_parse_int_header(response.headers.get("X-Pages")),
            error_limit_remain=_parse_int_header(
                response.headers.get("X-ESI-Error-Limit-Remain")
            ),
            error_limit_reset=_parse_int_header(
                response.headers.get("X-ESI-Error-Limit-Reset")
            ),
        )

    def _update_error_budget(self, response: httpx.Response) -> None:
        remain = _parse_int_header(response.headers.get("X-ESI-Error-Limit-Remain"))
        reset = _parse_int_header(response.headers.get("X-ESI-Error-Limit-Reset"))
        if remain is not None:
            self._error_limit_remain = remain
        if reset is not None:
            self._error_limit_reset = reset


def _cache_key(path: str, params: Params) -> tuple[str, tuple[tuple[str, str], ...]]:
    params_tuple = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
    return path, params_tuple


def _response_from_cache(entry: _CacheEntry) -> ESIResponse:
    return ESIResponse(
        data=entry.payload,
        expires=entry.expires,
        etag=entry.etag,
        pages=entry.pages,
        error_limit_remain=entry.error_limit_remain,
        error_limit_reset=entry.error_limit_reset,
    )


def _parse_expires(value: str | None, fallback: datetime) -> datetime:
    if value is None:
        return _ensure_utc(fallback)
    return _ensure_utc(parsedate_to_datetime(value))


def _parse_int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
