"""``neon_ping``: liveness and capability report."""

from __future__ import annotations

import time
from typing import Literal

from mcp.types import LATEST_PROTOCOL_VERSION
from pydantic import Field

from neon_mcp import __version__
from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import NeonInput, NeonOutput, Source, ToolResultBase
from neon_mcp.registry import register_tool

PING_PROBE_PATH = "/taxonomy"
PING_PROBE_PARAMS = {"taxonTypeCode": "TICK", "limit": 1}


class PingIn(NeonInput):
    check_api: bool = Field(
        False,
        description="Also make one tiny NEON request (~1 KB) to test reachability and read rate-limit headers.",
    )


class CatalogStatus(NeonOutput):
    products: Literal["cold", "warming", "warm", "degraded"]
    sites: Literal["cold", "warming", "warm", "degraded"]
    source: Literal["graphql", "rest"] | None = None
    age_seconds: int | None = None
    graphql_fallbacks: int = 0
    breaker_open: bool = False


class CacheInfo(NeonOutput):
    entries: int
    hits: int
    misses: int


class RateLimitInfo(NeonOutput):
    limit: int | None = None
    remaining: int | None = None
    reset_seconds: float | None = None
    identity: Literal["anonymous", "token"]


class ApiCheck(NeonOutput):
    reachable: bool
    latency_ms: int | None = None
    status: int | None = None
    error: str | None = None


class PingResult(ToolResultBase):
    pong: Literal["ok"] = "ok"
    version: str
    protocol_version: str
    transport: Literal["stdio", "http"]
    token_configured: bool = Field(
        description="True when this call has a NEON API token available."
    )
    token_source: Literal["config", "request", "none"]
    downloads_enabled: bool
    download_dir: str | None = None
    api_base_url: str
    graphql_url: str
    catalog: CatalogStatus
    cache: CacheInfo
    rate_limit: RateLimitInfo | None = None
    api: ApiCheck | None = None


@register_tool(
    "neon_ping",
    title="Check neon-mcp status",
    description=(
        "Liveness and capability report: server version and protocol, whether a NEON API token is "
        "available (it unlocks data files and sample views), whether downloads are enabled, catalog "
        "warmth, cache and rate-limit headroom. With check_api=true it makes one ~1 KB NEON request. "
        "Never reveals the token. Next: call neon_search_products to find a data product."
    ),
    input_model=PingIn,
    output_model=PingResult,
    surface="core",
    endpoints=["GET /taxonomy"],
)
async def neon_ping(args: PingIn, ctx: ToolContext) -> PingResult:
    api: ApiCheck | None = None
    source = Source(endpoints=[], via="local", cached=False)
    if args.check_api:
        started = time.monotonic()
        try:
            env = await ctx.client.get_json(
                PING_PROBE_PATH, PING_PROBE_PARAMS, token=ctx.token, stats=ctx.stats
            )
            api = ApiCheck(
                reachable=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                status=env.status,
            )
        except NeonApiError as exc:
            api = ApiCheck(
                reachable=exc.kind != "transport",
                status=exc.status or None,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=exc.detail[:200],
            )
        except ToolError as exc:
            api = ApiCheck(reachable=False, error=exc.message)
        source = Source(endpoints=[f"GET {PING_PROBE_PATH}"], via="rest", cached=False)

    identity = (
        ctx.token.identity()
        if ctx.token is not None
        and ctx.client.token_attached(ctx.client.url_for(PING_PROBE_PATH), ctx.token)
        else "anon"
    )
    snap = ctx.client.rate_limit_snapshot(identity)
    rate_limit = None
    if snap is not None:
        reset = None
        if snap.reset_at is not None:
            reset = max(round(snap.reset_at - time.monotonic(), 1), 0.0)
        rate_limit = RateLimitInfo(
            limit=snap.limit,
            remaining=snap.remaining,
            reset_seconds=reset,
            identity="token" if identity.startswith("tok:") else "anonymous",
        )
    warmth = ctx.catalog.warmth()
    cache = ctx.client.cache_stats()
    downloads = ctx.config.effective_downloads_enabled(ctx.transport)
    notes: list[str] = []
    steps = ["neon_search_products(query='breeding birds') to find a data product"]
    if ctx.token is None:
        notes.append(
            "No NEON API token: discovery, availability, taxonomy, releases, locations and prototype "
            "tools work; neon_list_files, neon_download_files and neon_get_sample need a token."
        )
        steps.append("Read neon://guide/api-token to enable file listing and downloads")
    elif api is not None and api.status == 403 and identity != "anon":
        notes.append(
            "NEON rejected the API token (HTTP 403 on a public endpoint): it is mistyped, "
            "disabled or deleted, and every request that carries it fails."
        )
        steps.append("Ask the user to fix or unset NEON_TOKEN (see neon://guide/api-token)")
    return PingResult(
        version=__version__,
        protocol_version=LATEST_PROTOCOL_VERSION,
        transport=ctx.transport,
        token_configured=ctx.token is not None,
        token_source=ctx.token_source,
        downloads_enabled=downloads,
        download_dir=str(ctx.config.downloads.directory) if downloads else None,
        api_base_url=ctx.client.base_url,
        graphql_url=ctx.client.graphql_url,
        catalog=CatalogStatus(
            products=warmth.products,
            sites=warmth.sites,
            source=warmth.source,
            age_seconds=warmth.age_s,
            graphql_fallbacks=warmth.graphql_fallbacks,
            breaker_open=warmth.breaker_open,
        ),
        cache=CacheInfo(entries=cache.entries, hits=cache.hits, misses=cache.misses),
        rate_limit=rate_limit,
        api=api,
        notes=notes,
        next_steps=steps,
        source=source,
    )
