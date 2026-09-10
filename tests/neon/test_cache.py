from __future__ import annotations

import asyncio

import anyio
import pytest

from neon_mcp.config import CacheConfig
from neon_mcp.neon.cache import FAMILY_CAPS, TTLCache, cache_key


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def counter(value: object = "v") -> tuple[list[int], object]:
    calls: list[int] = []

    async def fetch() -> object:
        calls.append(1)
        return value

    return calls, fetch


async def test_miss_then_hit_then_expiry() -> None:
    clock = Clock()
    cache = TTLCache(CacheConfig(), clock=clock)
    calls, fetch = counter()
    assert await cache.get_or_fetch("detail", "k", fetch) == ("v", "miss")  # type: ignore[arg-type]
    assert await cache.get_or_fetch("detail", "k", fetch) == ("v", "hit")  # type: ignore[arg-type]
    clock.now += 901
    assert (await cache.get_or_fetch("detail", "k", fetch))[1] == "miss"  # type: ignore[arg-type]
    assert len(calls) == 2
    assert cache.stats().hits == 1 and cache.stats().misses == 2


async def test_single_flight() -> None:
    cache = TTLCache(CacheConfig())
    gate = asyncio.Event()
    calls: list[int] = []

    async def fetch() -> str:
        calls.append(1)
        await gate.wait()
        return "built"

    tasks = [asyncio.create_task(cache.get_or_fetch("catalog", "idx", fetch)) for _ in range(10)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert calls == [1]
    assert {r[0] for r in results} == {"built"}


async def test_stale_if_error_window() -> None:
    clock = Clock()
    cache = TTLCache(CacheConfig(stale_if_error_s=100), clock=clock)
    _, fetch = counter("old")
    await cache.get_or_fetch("detail", "k", fetch)  # type: ignore[arg-type]

    async def boom() -> str:
        raise RuntimeError("upstream down")

    clock.now += 950
    assert await cache.get_or_fetch("detail", "k", boom) == ("old", "stale")
    assert cache.stats().stale_served == 1
    clock.now += 200
    with pytest.raises(RuntimeError):
        await cache.get_or_fetch("detail", "k", boom)


async def test_errors_are_not_cached() -> None:
    cache = TTLCache(CacheConfig())
    calls: list[int] = []

    async def flaky() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("once")
        return "ok"

    with pytest.raises(RuntimeError):
        await cache.get_or_fetch("detail", "k", flaky)
    assert await cache.get_or_fetch("detail", "k", flaky) == ("ok", "miss")


async def test_disabled_and_zero_ttl_bypass() -> None:
    calls, fetch = counter()
    off = TTLCache(CacheConfig(enabled=False))
    assert (await off.get_or_fetch("detail", "k", fetch))[1] == "bypass"  # type: ignore[arg-type]
    assert (await off.get_or_fetch("detail", "k", fetch))[1] == "bypass"  # type: ignore[arg-type]
    on = TTLCache(CacheConfig())
    assert (await on.get_or_fetch("detail", "k", fetch, ttl_s=0))[1] == "bypass"  # type: ignore[arg-type]
    assert len(calls) == 3


def test_lru_caps_invalidate_and_peek() -> None:
    clock = Clock()
    cache = TTLCache(CacheConfig(), clock=clock)
    cap = FAMILY_CAPS["documents"]
    for i in range(cap + 8):
        cache.put("documents", f"k{i}", i, ttl_s=60)
    assert cache.stats().families["documents"] == cap
    assert cache.peek("documents", "k0") is None
    assert cache.peek("documents", f"k{cap + 7}") == cap + 7
    clock.now += 61
    assert cache.peek("documents", f"k{cap + 7}") is None
    assert cache.invalidate("documents", "k10") == 1
    assert cache.invalidate() == cap - 1


def test_global_entry_cap() -> None:
    cache = TTLCache(CacheConfig(max_entries=10))
    for i in range(30):
        cache.put("taxonomy", f"k{i}", i, ttl_s=60)
    assert cache.stats().entries == 10


async def test_refresh_ahead_in_background() -> None:
    clock = Clock()
    cache = TTLCache(CacheConfig(refresh_ahead=0.5), clock=clock)
    values = iter(["v1", "v2"])

    async def fetch() -> str:
        return next(values)

    await cache.get_or_fetch("detail", "k", fetch, ttl_s=100)
    async with anyio.create_task_group() as tg:
        cache.start_background(tg)
        clock.now += 60  # inside the last 50 % of the TTL
        assert await cache.get_or_fetch("detail", "k", fetch, ttl_s=100) == ("v1", "hit")
    cache.start_background(None)
    assert cache.peek("detail", "k") == "v2"


def test_cache_key_is_canonical() -> None:
    a = cache_key("get", "/taxonomy", {"b": 2, "a": True, "z": None, "l": ["x", "y"]})
    b = cache_key("GET", "/taxonomy", {"l": ["x", "y"], "a": True, "b": 2})
    assert a == b == "GET /taxonomy?a=true&b=2&l=x&l=y"
    body1 = cache_key("POST", "/data/query", body={"x": 1, "y": [1, 2]})
    body2 = cache_key("POST", "/data/query", body={"y": [1, 2], "x": 1})
    assert body1 == body2 and "#" in body1
    assert cache_key("GET", "/data/x", token_scope="tok:abc").endswith("|tok:abc")
