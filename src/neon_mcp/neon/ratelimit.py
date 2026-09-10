"""Client-side rate limiting for the NEON API.

One token bucket per identity (``"anon"`` or a token's ``identity()``), set
10 % under NEON's published limits (anonymous 200 burst / 2 rps per IP; with
a token 2000 / 8 rps), re-synchronised from ``X-RateLimit-*`` response
headers, plus one process-wide concurrency semaphore. A 429 blocks the
identity for NEON's ``RetryAfter`` seconds.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from neon_mcp.config import RateLimitConfig
from neon_mcp.errors import ToolError


@dataclass
class RateLimitSnapshot:
    identity: str
    limit: int | None
    remaining: int | None
    reset_at: float | None
    bucket_tokens: float


@dataclass
class _Bucket:
    capacity: float
    rate: float
    tokens: float
    updated: float
    blocked_until: float = 0.0
    limit: int | None = None
    remaining: int | None = None
    reset_at: float | None = None


def _header_int(headers: Mapping[str, str], name: str) -> int | None:
    for key, value in headers.items():
        if key.lower() == name:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


class RateLimiter:
    def __init__(
        self,
        cfg: RateLimitConfig,
        *,
        max_concurrency: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._cfg = cfg
        self._clock = clock
        self._sleep = sleep
        self._buckets: dict[str, _Bucket] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _bucket(self, identity: str) -> _Bucket:
        bucket = self._buckets.get(identity)
        if bucket is None:
            if identity.startswith("tok:"):
                cap, rate = float(self._cfg.token_burst), self._cfg.token_rps
            else:
                cap, rate = float(self._cfg.anonymous_burst), self._cfg.anonymous_rps
            bucket = _Bucket(capacity=cap, rate=rate, tokens=cap, updated=self._clock())
            self._buckets[identity] = bucket
        return bucket

    @staticmethod
    def _refill(bucket: _Bucket, now: float) -> None:
        bucket.tokens = min(bucket.capacity, bucket.tokens + (now - bucket.updated) * bucket.rate)
        bucket.updated = now

    @asynccontextmanager
    async def concurrency(self) -> AsyncIterator[None]:
        """Only the process-wide semaphore (for non-NEON hosts such as signed GCS URLs)."""
        async with self._semaphore:
            yield

    @asynccontextmanager
    async def slot(self, identity: str) -> AsyncIterator[None]:
        """Wait for concurrency and rate headroom, then allow one request."""
        async with self._semaphore:
            await self._acquire(identity)
            yield

    async def _acquire(self, identity: str) -> None:
        bucket = self._bucket(identity)
        now = self._clock()
        wait = 0.0
        if bucket.blocked_until > now:
            wait = bucket.blocked_until - now
        elif (
            bucket.remaining is not None
            and bucket.remaining <= self._cfg.low_water
            and bucket.reset_at is not None
            and bucket.reset_at > now
        ):
            wait = bucket.reset_at - now
        self._refill(bucket, now)
        if bucket.tokens < 1.0:
            wait = max(wait, (1.0 - bucket.tokens) / bucket.rate)
        if wait > self._cfg.max_wait_s:
            raise ToolError(
                "rate_limited",
                "The NEON API rate limit has no headroom; wait before retrying.",
                details={
                    "retryAfterSeconds": round(wait, 2),
                    "limit": bucket.limit,
                    "remaining": bucket.remaining,
                    "identity": "token" if identity.startswith("tok:") else "anonymous",
                },
            )
        if wait > 0:
            await self._sleep(wait)
            now = self._clock()
            self._refill(bucket, now)
            bucket.remaining = None  # the reset we waited for has happened
        bucket.tokens = max(bucket.tokens - 1.0, -bucket.capacity)

    def observe(self, identity: str, headers: Mapping[str, str]) -> None:
        """Re-sync the identity's bucket from NEON's X-RateLimit-* headers."""
        limit = _header_int(headers, "x-ratelimit-limit")
        remaining = _header_int(headers, "x-ratelimit-remaining")
        reset = _header_int(headers, "x-ratelimit-reset")
        if limit is None and remaining is None:
            return
        bucket = self._bucket(identity)
        now = self._clock()
        bucket.limit = limit
        bucket.remaining = remaining
        bucket.reset_at = now + reset if reset is not None else None
        if remaining is not None:
            self._refill(bucket, now)
            bucket.tokens = min(bucket.tokens, float(remaining))

    def penalize(self, identity: str, retry_after_s: float) -> None:
        """After a 429, block this identity until ``now + retry_after_s``."""
        bucket = self._bucket(identity)
        bucket.blocked_until = max(bucket.blocked_until, self._clock() + max(retry_after_s, 0.0))

    def snapshot(self, identity: str) -> RateLimitSnapshot | None:
        bucket = self._buckets.get(identity)
        if bucket is None:
            return None
        return RateLimitSnapshot(
            identity=identity,
            limit=bucket.limit,
            remaining=bucket.remaining,
            reset_at=bucket.reset_at,
            bucket_tokens=round(bucket.tokens, 2),
        )
