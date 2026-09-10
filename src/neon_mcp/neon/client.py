"""The NEON Data API HTTP client.

One :class:`NeonClient` per process wraps one ``httpx.AsyncClient``. It
attaches ``X-API-Token`` only where DESIGN.md 3.2 allows (NEON hosts; token
endpoints always, public endpoints only when ``send_token_on_public``; never
signed storage URLs), runs every NEON request through the per-identity
:class:`RateLimiter`, retries 429 (honouring NEON's ``RetryAfter``), 5xx and
network failures with backoff, caches through :class:`TTLCache`, unwraps
NEON's ``{"data": ...}`` envelope and raises :class:`NeonApiError` for
failures. Redirects are never followed automatically: every hop is checked
against the download host allow-list.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypedDict, TypeVar
from urllib.parse import urljoin, urlsplit

import httpx
import structlog

from neon_mcp import __version__
from neon_mcp.config import NeonConfig
from neon_mcp.context import UpstreamStats
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.neon.auth import TOKEN_HEADER, Token, is_token_endpoint
from neon_mcp.neon.cache import CacheFamily, CacheHit, CacheStats, TTLCache, cache_key
from neon_mcp.neon.gql_queries import GqlQuery
from neon_mcp.neon.ratelimit import RateLimiter, RateLimitSnapshot

T = TypeVar("T")
log = structlog.get_logger("neon_mcp.http")

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = (
    "data.neonscience.org",
    "storage.googleapis.com",
    "*.storage.googleapis.com",
)
MAX_REDIRECTS = 3
_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)
_CONTENT_RANGE_RE = re.compile(r"/(\d+)\s*$")


class GraphQLPayload(TypedDict):
    data: Any | None
    errors: list[dict[str, Any]] | None


@dataclass
class Envelope(Generic[T]):
    data: T
    status: int
    headers: Mapping[str, str]
    cache: CacheHit
    elapsed_ms: float
    endpoint: str


@dataclass
class HeadInfo:
    url: str
    status: int
    content_type: str | None
    content_length: int | None
    filename: str | None


@dataclass
class StreamOutcome:
    path: Path
    bytes: int
    md5: str
    md5_verified: bool | None
    seconds: float


@dataclass
class _Decoded:
    data: Any
    status: int
    headers: dict[str, str]


def host_allowed(url: str, allowed: Sequence[str]) -> bool:
    """Suffix match on the URL host; ``*.example.org`` matches any subdomain."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    for pattern in allowed:
        pattern = pattern.lower().strip()
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            out[key] = [str(v) for v in value]
        else:
            out[key] = value
    return out


def _error_detail(body: Any, text: str) -> tuple[str, Any]:
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping) and err.get("detail"):
            return str(err["detail"]), body.get("data")
        if body.get("message"):
            return str(body["message"]), body.get("data")
        if body.get("errors"):
            first = body["errors"][0] if isinstance(body["errors"], list) and body["errors"] else {}
            return str(first.get("message", "GraphQL error")), body.get("data")
    return text[:300] or "no detail", None


class NeonClient:
    def __init__(
        self,
        config: NeonConfig,
        *,
        cache: TTLCache,
        limiter: RateLimiter,
        send_token_on_public: bool,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS,
    ) -> None:
        self.config = config
        self._cache = cache
        self._limiter = limiter
        self._send_token_on_public = send_token_on_public
        self._clock = clock
        self._sleep = sleep
        self._base = config.base_url.rstrip("/")
        self._base_path = urlsplit(self._base).path.rstrip("/")
        self._graphql_url = config.graphql_url
        self._neon_hosts = {
            (urlsplit(self._base).hostname or "").lower(),
            (urlsplit(self._graphql_url).hostname or "").lower(),
        }
        self.allowed_hosts = tuple(allowed_hosts)
        suffix = f" {config.user_agent_suffix}" if config.user_agent_suffix else ""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout_s, read=config.read_timeout_s, write=10.0, pool=10.0
            ),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers={
                "User-Agent": f"neon-mcp/{__version__} (+https://github.com/idss-mesa/neon-mcp){suffix}",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
            follow_redirects=False,
            transport=transport,
        )

    # ------------------------------------------------------------------ helpers

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def graphql_url(self) -> str:
        return self._graphql_url

    def url_for(self, path: str) -> str:
        return path if path.startswith(("http://", "https://")) else f"{self._base}{path}"

    def _relative(self, url: str) -> str:
        parts = urlsplit(url)
        if (parts.hostname or "").lower() in self._neon_hosts and parts.path.startswith(
            self._base_path
        ):
            return parts.path[len(self._base_path) :] or "/"
        return parts.path

    def is_neon_url(self, url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in self._neon_hosts

    def token_attached(self, url: str, token: Token | None) -> bool:
        """Whether a request to ``url`` would carry ``token``."""
        if token is None or not self.is_neon_url(url):
            return False
        return is_token_endpoint(self._relative(url)) or self._send_token_on_public

    def _timeout(self, read_s: float | None) -> httpx.Timeout | None:
        if read_s is None:
            return None
        return httpx.Timeout(
            connect=self.config.connect_timeout_s, read=read_s, write=10.0, pool=10.0
        )

    async def _backoff(self, attempt: int) -> None:
        retries = self.config.retries
        delay = min(retries.backoff_base_s * (2 ** (attempt - 1)), retries.backoff_max_s)
        await self._sleep(delay + random.uniform(0, 0.25))  # noqa: S311 - jitter, not crypto

    def _retry_after(self, headers: Mapping[str, str]) -> float:
        for name in ("retryafter", "retry-after"):
            for key, value in headers.items():
                if key.lower() == name:
                    try:
                        return max(float(value), 0.0)
                    except ValueError:
                        pass
        return self.config.retries.retry_after_default_s

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        token: Token | None,
        stats: UpstreamStats,
        timeout_s: float | None = None,
        extra_headers: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> tuple[httpx.Response, bool]:
        """Send with retries; returns ``(response, token_attached)``."""
        rel = self._relative(url)
        attached = self.token_attached(url, token)
        headers = dict(extra_headers or {})
        if attached and token is not None:
            headers[TOKEN_HEADER] = token.value
        identity = token.identity() if attached and token is not None else "anon"
        neon = self.is_neon_url(url)
        attempts = self.config.retries.max_attempts
        for attempt in range(1, attempts + 1):
            started = self._clock()
            try:
                request = self._http.build_request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self._timeout(timeout_s) or httpx.USE_CLIENT_DEFAULT,
                )
                limiter_cm = self._limiter.slot(identity) if neon else self._limiter.concurrency()
                async with limiter_cm:
                    response = await self._http.send(request, stream=stream)
            except httpx.HTTPError as exc:
                if attempt < attempts:
                    await self._backoff(attempt)
                    continue
                raise NeonApiError(
                    0, type(exc).__name__, rel, kind="transport", token_sent=attached
                ) from exc
            stats.requests += 1
            if neon:
                self._limiter.observe(identity, response.headers)
                snap = self._limiter.snapshot(identity)
                if snap is not None:
                    stats.rate_limit_remaining = snap.remaining
                    stats.rate_limit_limit = snap.limit
                if attached:
                    stats.identity = "token"
            log.debug(
                "neon.http",
                method=method,
                path=rel,
                query_keys=sorted(params or {}),
                status=response.status_code,
                ms=round((self._clock() - started) * 1000, 1),
                attempt=attempt,
                identity="token" if attached else "anonymous",
            )
            if response.status_code == 429:
                retry_after = self._retry_after(response.headers)
                if neon:
                    self._limiter.penalize(identity, retry_after)
                if attempt < attempts:
                    await response.aclose()
                    await self._sleep(retry_after)
                    continue
                body_text = (await response.aread()).decode("utf-8", "replace")
                await response.aclose()
                raise NeonApiError(
                    429,
                    "API rate limit exceeded",
                    rel,
                    retry_after_s=retry_after,
                    headers=dict(response.headers),
                    data=body_text[:200],
                    token_sent=attached,
                )
            if response.status_code >= 500 and attempt < attempts:
                await response.aclose()
                await self._backoff(attempt)
                continue
            return response, attached
        raise AssertionError("unreachable")  # pragma: no cover

    def _decode(
        self, response: httpx.Response, rel: str, attached: bool, *, unwrap: bool
    ) -> _Decoded:
        text = response.text
        content_type = response.headers.get("content-type")
        try:
            body = json.loads(text) if text else None
        except ValueError:
            if response.status_code >= 400:
                raise NeonApiError(
                    response.status_code,
                    text[:300],
                    rel,
                    headers=dict(response.headers),
                    token_sent=attached,
                ) from None
            raise NeonApiError(
                response.status_code,
                "response is not JSON",
                rel,
                kind="decode",
                content_type=content_type,
                token_sent=attached,
            ) from None
        if response.status_code >= 400:
            detail, data = _error_detail(body, text)
            raise NeonApiError(
                response.status_code,
                detail,
                rel,
                data=data,
                headers=dict(response.headers),
                retry_after_s=self._retry_after(response.headers)
                if response.status_code == 429
                else None,
                token_sent=attached,
            )
        if unwrap and isinstance(body, dict) and set(body) == {"data"}:
            body = body["data"]
        return _Decoded(data=body, status=response.status_code, headers=dict(response.headers))

    async def _cached(
        self,
        family: CacheFamily | None,
        key: str,
        ttl_s: float | None,
        stats: UpstreamStats,
        fetch: Callable[[], Awaitable[_Decoded]],
    ) -> tuple[_Decoded, CacheHit]:
        if family is None:
            return await fetch(), "bypass"
        value, hit = await self._cache.get_or_fetch(family, key, fetch, ttl_s=ttl_s)
        if hit in ("hit", "stale"):
            stats.cache_hits += 1
        return value, hit

    # ------------------------------------------------------------------ JSON

    async def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        token: Token | None,
        cache: CacheFamily | None = None,
        ttl_s: float | None = None,
        timeout_s: float | None = None,
        stats: UpstreamStats | None = None,
    ) -> Envelope[Any]:
        stats = stats if stats is not None else UpstreamStats()
        url = self.url_for(path)
        rel = self._relative(url)
        clean = _clean_params(params)
        endpoint = f"GET {rel}"
        stats.record_endpoint(endpoint)
        scope = token.identity() if token is not None and is_token_endpoint(rel) else None
        started = self._clock()

        async def fetch() -> _Decoded:
            response, attached = await self._send(
                "GET", url, params=clean, token=token, stats=stats, timeout_s=timeout_s
            )
            return self._decode(response, rel, attached, unwrap=True)

        decoded, hit = await self._cached(
            cache, cache_key("GET", rel, clean, token_scope=scope), ttl_s, stats, fetch
        )
        return Envelope(
            data=decoded.data,
            status=decoded.status,
            headers=decoded.headers,
            cache=hit,
            elapsed_ms=round((self._clock() - started) * 1000, 1),
            endpoint=endpoint,
        )

    async def post_json(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        token: Token | None,
        cache: CacheFamily | None = None,
        ttl_s: float | None = None,
        timeout_s: float | None = None,
        stats: UpstreamStats | None = None,
    ) -> Envelope[Any]:
        stats = stats if stats is not None else UpstreamStats()
        url = self.url_for(path)
        rel = self._relative(url)
        endpoint = f"POST {rel}"
        stats.record_endpoint(endpoint)
        scope = token.identity() if token is not None and is_token_endpoint(rel) else None
        started = self._clock()

        async def fetch() -> _Decoded:
            response, attached = await self._send(
                "POST", url, json_body=dict(body), token=token, stats=stats, timeout_s=timeout_s
            )
            return self._decode(response, rel, attached, unwrap=True)

        key = cache_key("POST", rel, None, body=dict(body), token_scope=scope)
        decoded, hit = await self._cached(cache, key, ttl_s, stats, fetch)
        return Envelope(
            data=decoded.data,
            status=decoded.status,
            headers=decoded.headers,
            cache=hit,
            elapsed_ms=round((self._clock() - started) * 1000, 1),
            endpoint=endpoint,
        )

    async def graphql(
        self,
        query: GqlQuery | str,
        variables: Mapping[str, Any] | None = None,
        *,
        operation_name: str | None = None,
        token: Token | None = None,
        cache: CacheFamily | None = None,
        ttl_s: float | None = None,
        timeout_s: float | None = 30.0,
        stats: UpstreamStats | None = None,
    ) -> Envelope[GraphQLPayload]:
        """POST a GraphQL document. HTTP-level failures raise; ``errors`` are returned."""
        stats = stats if stats is not None else UpstreamStats()
        document = query.document if isinstance(query, GqlQuery) else query
        op = operation_name or (query.name if isinstance(query, GqlQuery) else None)
        body: dict[str, Any] = {"query": document}
        if variables:
            body["variables"] = dict(variables)
        if op:
            body["operationName"] = op
        endpoint = "POST /graphql"
        stats.record_endpoint(endpoint)
        started = self._clock()

        async def fetch() -> _Decoded:
            response, attached = await self._send(
                "POST",
                self._graphql_url,
                json_body=body,
                token=token,
                stats=stats,
                timeout_s=timeout_s,
            )
            text = response.text
            try:
                parsed = json.loads(text) if text else None
            except ValueError:
                raise NeonApiError(
                    response.status_code,
                    "GraphQL response is not JSON",
                    "/graphql",
                    kind="decode",
                    content_type=response.headers.get("content-type"),
                    token_sent=attached,
                ) from None
            if isinstance(parsed, dict) and ("data" in parsed or "errors" in parsed):
                payload: GraphQLPayload = {
                    "data": parsed.get("data"),
                    "errors": parsed.get("errors"),
                }
                return _Decoded(
                    data=payload, status=response.status_code, headers=dict(response.headers)
                )
            detail, data = _error_detail(parsed, text)
            raise NeonApiError(
                response.status_code, detail, "/graphql", data=data, token_sent=attached
            )

        key = cache_key("POST", "/graphql", None, body=body)
        decoded, hit = await self._cached(cache, key, ttl_s, stats, fetch)
        return Envelope(
            data=decoded.data,
            status=decoded.status,
            headers=decoded.headers,
            cache=hit,
            elapsed_ms=round((self._clock() - started) * 1000, 1),
            endpoint=endpoint,
        )

    # ------------------------------------------------------------------ binary

    async def _open(
        self,
        url: str,
        *,
        method: str = "GET",
        token: Token | None,
        stats: UpstreamStats,
        allowed_hosts: Sequence[str] | None,
        extra_headers: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> tuple[httpx.Response, str]:
        """Open a streamed response, following up to 3 allow-listed redirects."""
        allowed = tuple(allowed_hosts) if allowed_hosts is not None else self.allowed_hosts
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            if not host_allowed(current, allowed):
                raise ToolError(
                    "download_denied",
                    "Refusing to fetch from a host outside the download allow-list.",
                    details={"host": urlsplit(current).hostname, "allowedHosts": list(allowed)},
                )
            stats.record_endpoint(
                f"{method} {self._relative(current)}"
                if self.is_neon_url(current)
                else f"{method} {urlsplit(current).hostname}"
            )
            response, attached = await self._send(
                method,
                current,
                token=token,
                stats=stats,
                stream=True,
                extra_headers=extra_headers,
                timeout_s=timeout_s,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise NeonApiError(
                        response.status_code, "redirect without Location", self._relative(current)
                    )
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                await response.aread()
                await response.aclose()
                self._decode(response, self._relative(current), attached, unwrap=True)
            return response, current
        raise ToolError(
            "download_denied", "Too many redirects.", details={"url": url.split("?")[0]}
        )

    async def head(
        self,
        path_or_url: str,
        *,
        token: Token | None,
        stats: UpstreamStats | None = None,
    ) -> HeadInfo:
        """Metadata of a binary resource: HEAD, falling back to a 1-byte ranged GET."""
        stats = stats if stats is not None else UpstreamStats()
        url = self.url_for(path_or_url)
        try:
            response, final = await self._open(
                url, method="HEAD", token=token, stats=stats, allowed_hosts=None
            )
        except NeonApiError as exc:
            if exc.status not in (403, 405, 501):
                raise
            response, final = await self._open(
                url,
                token=token,
                stats=stats,
                allowed_hosts=None,
                extra_headers={"Range": "bytes=0-0"},
            )
        await response.aclose()
        length: int | None = None
        content_range = response.headers.get("content-range")
        if content_range and (m := _CONTENT_RANGE_RE.search(content_range)):
            length = int(m.group(1))
        elif response.headers.get("content-length", "").isdigit():
            length = int(response.headers["content-length"])
        disposition = response.headers.get("content-disposition") or ""
        match = _FILENAME_RE.search(disposition)
        return HeadInfo(
            url=final,
            status=response.status_code,
            content_type=(response.headers.get("content-type") or "").split(";")[0] or None,
            content_length=length,
            filename=match.group(1) if match else None,
        )

    async def resolve_redirect(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        token: Token | None,
        stats: UpstreamStats | None = None,
    ) -> str | None:
        """GET without following; a 30x returns its ``Location``, a 200 returns ``None``."""
        stats = stats if stats is not None else UpstreamStats()
        url = self.url_for(path)
        rel = self._relative(url)
        stats.record_endpoint(f"GET {rel}")
        response, attached = await self._send(
            "GET", url, params=_clean_params(params), token=token, stats=stats, stream=True
        )
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                return urljoin(url, location) if location else None
            if response.status_code >= 400:
                await response.aread()
                self._decode(response, rel, attached, unwrap=True)
            return None
        finally:
            await response.aclose()

    async def fetch_bytes(
        self,
        url: str,
        *,
        token: Token | None,
        max_bytes: int,
        stats: UpstreamStats | None = None,
        allowed_hosts: Sequence[str] | None = None,
    ) -> bytes:
        """Download a body into memory, aborting beyond ``max_bytes``."""
        stats = stats if stats is not None else UpstreamStats()
        response, _ = await self._open(
            self.url_for(url),
            token=token,
            stats=stats,
            allowed_hosts=allowed_hosts,
            timeout_s=self.config.download_read_timeout_s,
        )
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ToolError(
                        "result_too_large",
                        f"The document is larger than the {max_bytes}-byte limit.",
                        details={"maxBytes": max_bytes},
                    )
                chunks.append(chunk)
        finally:
            await response.aclose()
        return b"".join(chunks)

    async def stream_to_file(
        self,
        url: str,
        dest: Path,
        *,
        token: Token | None,
        max_bytes: int,
        expected_md5: str | None,
        stats: UpstreamStats | None = None,
        allowed_hosts: Sequence[str] | None = None,
    ) -> StreamOutcome:
        """Stream to ``dest.part`` then ``os.replace``; verify MD5 when known."""
        stats = stats if stats is not None else UpstreamStats()
        started = self._clock()
        partial = dest.with_name(dest.name + ".part")
        digest = hashlib.md5(usedforsecurity=False)
        total = 0
        response, _ = await self._open(
            self.url_for(url),
            token=token,
            stats=stats,
            allowed_hosts=allowed_hosts,
            timeout_s=self.config.download_read_timeout_s,
        )
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ToolError(
                            "download_limit_exceeded",
                            f"{dest.name} exceeds the per-file limit of {max_bytes} bytes.",
                            details={"file": dest.name, "maxBytes": max_bytes},
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            md5 = digest.hexdigest()
            verified: bool | None = None
            if expected_md5:
                verified = md5.lower() == expected_md5.lower()
                if not verified:
                    raise ToolError(
                        "checksum_mismatch",
                        f"MD5 of {dest.name} does not match NEON's checksum; the partial file was removed.",
                        details={"file": dest.name, "expected": expected_md5, "actual": md5},
                    )
            os.replace(partial, dest)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        finally:
            await response.aclose()
        return StreamOutcome(
            path=dest,
            bytes=total,
            md5=md5,
            md5_verified=verified,
            seconds=round(self._clock() - started, 3),
        )

    # ------------------------------------------------------------------ misc

    def rate_limit_snapshot(self, identity: str) -> RateLimitSnapshot | None:
        return self._limiter.snapshot(identity)

    def cache_stats(self) -> CacheStats:
        return self._cache.stats()

    @property
    def cache(self) -> TTLCache:
        return self._cache

    async def aclose(self) -> None:
        await self._http.aclose()
