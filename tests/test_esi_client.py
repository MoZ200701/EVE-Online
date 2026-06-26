from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from evemarket.config import Config
from evemarket.esi.client import ERROR_LIMIT_THRESHOLD, ESIClient
from evemarket.esi.models import MarketOrder


def order_payload(order_id: int = 1) -> dict:
    return {
        "order_id": order_id,
        "type_id": 34,
        "is_buy_order": False,
        "price": 6.25,
        "volume_remain": 100,
        "volume_total": 200,
        "min_volume": 1,
        "location_id": 60003760,
        "system_id": 30000142,
        "range": "region",
        "duration": 90,
        "issued": "2026-06-25T12:00:00Z",
    }


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 6, 26, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def esi_headers(
    clock: Clock,
    *,
    pages: int | None = 1,
    etag: str | None = '"abc"',
    remain: int = 100,
    reset: int = 1,
    expires_delta: int = 60,
) -> dict[str, str]:
    headers = {
        "Expires": format_datetime(clock() + timedelta(seconds=expires_delta)),
        "X-ESI-Error-Limit-Remain": str(remain),
        "X-ESI-Error-Limit-Reset": str(reset),
    }
    if pages is not None:
        headers["X-Pages"] = str(pages)
    if etag is not None:
        headers["ETag"] = etag
    return headers


def run(coro):
    return asyncio.run(coro)


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    clock: Clock,
    sleeps: list[float] | None = None,
) -> ESIClient:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return ESIClient(
        config=Config(user_agent="eve-market-tool/0.1 (contact: test@example.com)"),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        now=clock,
        backoff_base_seconds=0.01,
    )


def test_paginated_fetches_all_pages_in_order() -> None:
    clock = Clock()
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        requested_pages.append(page)
        return httpx.Response(
            200,
            headers=esi_headers(clock, pages=3),
            json=[{"page": page}],
        )

    async def scenario() -> list[dict]:
        async with make_client(handler, clock) as client:
            return await client.get_paginated("/latest/markets/10000002/orders/")

    assert run(scenario()) == [{"page": 1}, {"page": 2}, {"page": 3}]
    assert sorted(requested_pages) == [1, 2, 3]


def test_cache_hit_before_expires_makes_no_new_request() -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers=esi_headers(clock),
            json={"ok": True},
        )

    async def scenario() -> tuple[object, object]:
        async with make_client(handler, clock) as client:
            first = await client.get("/latest/status/")
            second = await client.get("/latest/status/")
        return first.data, second.data

    assert run(scenario()) == ({"ok": True}, {"ok": True})
    assert calls == 1


def test_304_uses_cached_payload_after_expiry() -> None:
    clock = Clock()
    seen_if_none_match: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_if_none_match.append(request.headers.get("If-None-Match"))
        if len(seen_if_none_match) == 1:
            return httpx.Response(
                200,
                headers=esi_headers(clock, etag='"cached"', expires_delta=5),
                json={"cached": True},
            )
        return httpx.Response(
            304,
            headers=esi_headers(clock, etag='"cached"', expires_delta=60),
        )

    async def scenario() -> object:
        async with make_client(handler, clock) as client:
            await client.get("/latest/status/")
            clock.advance(10)
            second = await client.get("/latest/status/")
        return second.data

    assert run(scenario()) == {"cached": True}
    assert seen_if_none_match == [None, '"cached"']


def test_error_budget_low_remain_sleeps_before_next_request() -> None:
    clock = Clock()
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        remain = ERROR_LIMIT_THRESHOLD if calls == 1 else 100
        return httpx.Response(
            200,
            headers=esi_headers(clock, remain=remain, reset=7),
            json={"call": calls},
        )

    async def scenario() -> None:
        async with make_client(handler, clock, sleeps) as client:
            await client.get("/latest/one/")
            await client.get("/latest/two/")

    run(scenario())

    assert sleeps == [7.0]
    assert calls == 2


def test_retries_5xx_then_succeeds() -> None:
    clock = Clock()
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(500, headers=esi_headers(clock), json={})
        return httpx.Response(200, headers=esi_headers(clock), json={"ok": True})

    async def scenario() -> object:
        async with make_client(handler, clock, sleeps) as client:
            response = await client.get("/latest/status/")
        return response.data

    assert run(scenario()) == {"ok": True}
    assert calls == 3
    assert sleeps == [0.01, 0.02]


def test_market_order_parses_representative_payload() -> None:
    order = MarketOrder.model_validate(order_payload())

    assert order.order_id == 1
    assert order.type_id == 34
    assert order.issued == datetime(2026, 6, 25, 12, tzinfo=timezone.utc)


@pytest.mark.skipif(
    os.environ.get("EVEMARKET_LIVE_TESTS") != "1",
    reason="Set EVEMARKET_LIVE_TESTS=1 to run live ESI tests.",
)
def test_live_forge_orders() -> None:
    async def scenario() -> tuple[int, int | None]:
        async with ESIClient(
            config=Config(user_agent="eve-market-tool/0.1 (contact: Discord m0obot)")
        ) as client:
            response = await client.get(
                "/latest/markets/10000002/orders/",
                params={"order_type": "all", "page": 1},
            )
        orders = [MarketOrder.model_validate(order) for order in response.data]
        return len(orders), response.pages

    order_count, pages = run(scenario())

    assert order_count >= 1
    assert pages is not None
