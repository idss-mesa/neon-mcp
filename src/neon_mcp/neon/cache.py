"""In-memory TTL cache with single-flight, refresh-ahead and stale-if-error.

Entries live in per-family LRU maps. Concurrent misses on one key perform a
single fetch (critical for multi-megabyte catalog builds). In HTTP mode a
background task group refreshes entries that are close to expiry; an
expired entry is served (reported as ``stale``) for up to
``cache.stale_if_error_s`` when its refresh fails.

Cache keys for public endpoints never contain a token; token-endpoint keys
carry only the token's non-reversible ``identity()``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar
from urllib.parse import urlencode

import anyio.abc
import structlog

from neon_mcp.config import CacheConfig

T = TypeVar("T")

CacheFamily = Literal[
    "catalog",
    "detail",
    "locations",
    "releases",
    "taxonomy",
    "samples_classes",
    "samples_view",
    "data",
    "prototype",
    "documents",
]
CacheHit = Literal["hit", "miss", "stale", "refreshed", "bypass"]

FAMILY_CAPS: dict[str, int] = {
    "catalog": 36,
    "detail": 64,
    "locations": 256,
    "releases": 32,
    "taxonomy": 256,
    "samples_classes": 128,
    "samples_view": 64,
    "data": 128,
    "prototype": 64,
    "documents": 32,
}

log = structlog.get_logger("neon_mcp.cache")


@dataclass
class _Entry:
    value: Any
    expires_at: float
    ttl: float


@dataclass
class CacheStats:
    entries: int
    hits: int
    misses: int
    stale_served: int
    families: dict[str, int] = field(default_factory=dict)


def _fmt(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return [_fmt(v) for v in value]
    return value


def cache_key(
    method: str,
    path: str,
    params: Mapping[str, Any] | None = None,
    *,
    body: Any = None,
    token_scope: str | None = None,
) -> str:
    """Canonical key: method, path, sorted query, body hash, token identity."""
    items = sorted((k, _fmt(v)) for k, v in (params or {}).items() if v is not None)
    key = f"{method.upper()} {path}?{urlencode(items, doseq=True)}"
    if body is not None:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        key += "#" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    if token_scope:
        key += "|" + token_scope
    return key


class TTLCache:
    def __init__(self, cfg: CacheConfig, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._cfg = cfg
        self._clock = clock
        self._data: dict[str, OrderedDict[str, _Entry]] = {f: OrderedDict() for f in FAMILY_CAPS}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._refreshing: set[tuple[str, str]] = set()
        self._tg: anyio.abc.TaskGroup | None = None
        self.hits = 0
        self.misses = 0
        self.stale_served = 0

    def ttl_for(self, family: CacheFamily) -> float:
        return float(getattr(self._cfg.ttl_s, family))

    def start_background(self, tg: anyio.abc.TaskGroup | None) -> None:
        """Enable (or, with ``None``, disable) background refresh-ahead."""
        self._tg = tg

    def _entry(self, family: str, key: str) -> _Entry | None:
        return self._data[family].get(key)

    async def get_or_fetch(
        self,
        family: CacheFamily,
        key: str,
        fetch: Callable[[], Awaitable[T]],
        *,
        ttl_s: float | None = None,
        stale_if_error: bool = True,
    ) -> tuple[T, CacheHit]:
        ttl = self.ttl_for(family) if ttl_s is None else float(ttl_s)
        if not self._cfg.enabled or ttl <= 0:
            return await fetch(), "bypass"

        entry = self._entry(family, key)
        now = self._clock()
        if entry is not None and now < entry.expires_at:
            self.hits += 1
            self._data[family].move_to_end(key)
            self._maybe_refresh_ahead(family, key, entry, fetch, ttl, now)
            return entry.value, "hit"

        lock = self._locks.setdefault((family, key), asyncio.Lock())
        try:
            async with lock:
                entry = self._entry(family, key)
                now = self._clock()
                if entry is not None and now < entry.expires_at:
                    self.hits += 1
                    return entry.value, "hit"
                self.misses += 1
                try:
                    value = await fetch()
                except Exception:
                    if (
                        stale_if_error
                        and entry is not None
                        and now - entry.expires_at <= self._cfg.stale_if_error_s
                    ):
                        self.stale_served += 1
                        log.warning(
                            "cache.stale_served",
                            family=family,
                            age_s=round(now - entry.expires_at, 1),
                        )
                        return entry.value, "stale"
                    raise
                self.put(family, key, value, ttl_s=ttl)
                return value, "miss"
        finally:
            if not lock.locked():
                self._locks.pop((family, key), None)

    def _maybe_refresh_ahead(
        self,
        family: CacheFamily,
        key: str,
        entry: _Entry,
        fetch: Callable[[], Awaitable[Any]],
        ttl: float,
        now: float,
    ) -> None:
        if self._tg is None or self._cfg.refresh_ahead <= 0:
            return
        if entry.expires_at - now > ttl * self._cfg.refresh_ahead:
            return
        marker = (family, key)
        if marker in self._refreshing:
            return
        self._refreshing.add(marker)
        self._tg.start_soon(self._refresh, family, key, fetch, ttl)

    async def _refresh(
        self, family: CacheFamily, key: str, fetch: Callable[[], Awaitable[Any]], ttl: float
    ) -> None:
        try:
            value = await fetch()
            self.put(family, key, value, ttl_s=ttl)
            log.debug("cache.refresh", family=family)
        except Exception as exc:  # keep serving the current value
            log.warning("cache.refresh_failed", family=family, error=type(exc).__name__)
        finally:
            self._refreshing.discard((family, key))

    def peek(self, family: CacheFamily, key: str) -> Any | None:
        entry = self._entry(family, key)
        if entry is None or self._clock() >= entry.expires_at:
            return None
        return entry.value

    def put(self, family: CacheFamily, key: str, value: Any, *, ttl_s: float) -> None:
        if not self._cfg.enabled or ttl_s <= 0:
            return
        bucket = self._data[family]
        bucket[key] = _Entry(value=value, expires_at=self._clock() + ttl_s, ttl=ttl_s)
        bucket.move_to_end(key)
        cap = FAMILY_CAPS[family]
        while len(bucket) > cap:
            bucket.popitem(last=False)
        while sum(len(b) for b in self._data.values()) > self._cfg.max_entries:
            largest = max(self._data.values(), key=len)
            largest.popitem(last=False)

    def invalidate(self, family: CacheFamily | None = None, key: str | None = None) -> int:
        removed = 0
        families = [family] if family else list(self._data)
        for fam in families:
            bucket = self._data[fam]
            if key is None:
                removed += len(bucket)
                bucket.clear()
            elif bucket.pop(key, None) is not None:
                removed += 1
        return removed

    def stats(self) -> CacheStats:
        families = {name: len(bucket) for name, bucket in self._data.items() if bucket}
        return CacheStats(
            entries=sum(families.values()),
            hits=self.hits,
            misses=self.misses,
            stale_served=self.stale_served,
            families=families,
        )
