from __future__ import annotations

import asyncio

import pytest

from neon_mcp.config import RateLimitConfig
from neon_mcp.errors import ToolError
from neon_mcp.neon.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def limiter(clock: Clock, **cfg: float) -> RateLimiter:
    base = {
        "anonymous_burst": 3,
        "anonymous_rps": 1.0,
        "token_burst": 10,
        "token_rps": 5.0,
        "low_water": 2,
        "max_wait_s": 10.0,
    }
    base.update(cfg)
    return RateLimiter(RateLimitConfig(**base), max_concurrency=4, clock=clock, sleep=clock.sleep)  # type: ignore[arg-type]


async def test_burst_then_refill_wait() -> None:
    clock = Clock()
    rl = limiter(clock)
    for _ in range(3):
        async with rl.slot("anon"):
            pass
    assert clock.sleeps == []
    async with rl.slot("anon"):
        pass
    assert clock.sleeps == [1.0]


async def test_wait_beyond_max_is_rate_limited() -> None:
    clock = Clock()
    rl = limiter(clock, anonymous_burst=1, anonymous_rps=0.01)
    async with rl.slot("anon"):
        pass
    with pytest.raises(ToolError) as exc:
        async with rl.slot("anon"):
            pass
    assert exc.value.code == "rate_limited"
    assert exc.value.details["retryAfterSeconds"] > 10


async def test_low_water_waits_for_reset_once() -> None:
    clock = Clock()
    rl = limiter(clock, anonymous_burst=100)
    rl.observe(
        "anon", {"X-RateLimit-Limit": "200", "X-RateLimit-Remaining": "2", "X-RateLimit-Reset": "4"}
    )
    async with rl.slot("anon"):
        pass
    assert clock.sleeps == [4.0]
    async with rl.slot("anon"):
        pass
    assert clock.sleeps == [4.0]


async def test_observe_clamps_bucket_and_snapshot() -> None:
    clock = Clock()
    rl = limiter(clock, anonymous_burst=100)
    assert rl.snapshot("anon") is None
    rl.observe("anon", {"x-ratelimit-limit": "200", "x-ratelimit-remaining": "40"})
    snap = rl.snapshot("anon")
    assert (
        snap is not None and snap.limit == 200 and snap.remaining == 40 and snap.bucket_tokens <= 40
    )
    rl.observe("anon", {"content-type": "json"})  # no rate headers: ignored
    assert rl.snapshot("anon").remaining == 40  # type: ignore[union-attr]


async def test_penalize_blocks_identity_only() -> None:
    clock = Clock()
    rl = limiter(clock)
    rl.penalize("anon", 2.0)
    async with rl.slot("tok:abc"):
        pass
    assert clock.sleeps == []
    async with rl.slot("anon"):
        pass
    assert clock.sleeps == [2.0]


async def test_token_identity_uses_token_tier() -> None:
    clock = Clock()
    rl = limiter(clock)
    for _ in range(10):
        async with rl.slot("tok:abc"):
            pass
    assert clock.sleeps == []
    async with rl.slot("tok:abc"):
        pass
    assert clock.sleeps == [0.2]


async def test_concurrency_semaphore() -> None:
    rl = RateLimiter(RateLimitConfig(), max_concurrency=1)
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with rl.slot("anon"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 1
