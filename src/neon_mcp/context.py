"""Per-call context handed to every tool handler.

Handlers take ``(args, ctx)``. :class:`ToolContext` carries the process-wide
collaborators (config, NEON client, catalog), the call's resolved NEON token
(never logged), the caller's MRTR capability, and an :class:`UpstreamStats`
accumulator that feeds the ``io.neon-mcp/upstream`` result ``_meta``.

HTTP-scoped values (request headers, request id) reach the MCP adapter
through the context variables below, set by
:class:`neon_mcp.transport.streamable_http.RequestContextMiddleware`.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from neon_mcp.config import Config
    from neon_mcp.neon.auth import Token
    from neon_mcp.neon.catalog import Catalog
    from neon_mcp.neon.client import NeonClient

TransportName = Literal["stdio", "http"]

current_transport: ContextVar[TransportName | None] = ContextVar("neon_mcp_transport", default=None)
current_request_headers: ContextVar[Mapping[str, str] | None] = ContextVar(
    "neon_mcp_request_headers", default=None
)
current_request_id: ContextVar[str | None] = ContextVar("neon_mcp_request_id", default=None)


@dataclass
class UpstreamStats:
    """What one tool call cost upstream (reported in result ``_meta``)."""

    requests: int = 0
    cache_hits: int = 0
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None
    identity: Literal["anonymous", "token"] = "anonymous"
    endpoints: list[str] = field(default_factory=list)

    def record_endpoint(self, endpoint: str) -> None:
        if endpoint not in self.endpoints:
            self.endpoints.append(endpoint)

    def as_meta(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "cacheHits": self.cache_hits,
            "rateLimitRemaining": self.rate_limit_remaining,
            "rateLimitLimit": self.rate_limit_limit,
            "identity": self.identity,
        }


@dataclass(frozen=True)
class Elicited:
    """An MRTR follow-up: the user's answers plus the decoded continuation."""

    responses: Mapping[str, Any]
    state: Mapping[str, Any]


@dataclass(frozen=True)
class ToolContext:
    config: Config
    client: NeonClient
    catalog: Catalog
    transport: TransportName
    tool_name: str
    token: Token | None
    client_capabilities: Mapping[str, Any]
    elicitation_supported: bool
    elicited: Elicited | None
    request_id: str | None
    stats: UpstreamStats
    log: Any

    @property
    def token_source(self) -> Literal["config", "request", "none"]:
        return self.token.source if self.token is not None else "none"


def build_tool_context(
    *,
    config: Config,
    client: NeonClient,
    catalog: Catalog,
    transport: TransportName,
    tool_name: str,
    client_capabilities: Mapping[str, Any] | None = None,
    elicited: Elicited | None = None,
    request_id: str | None = None,
    request_headers: Mapping[str, str] | None = None,
    stats: UpstreamStats | None = None,
) -> ToolContext:
    """Resolve the call's token and assemble a :class:`ToolContext`."""
    from neon_mcp.neon.auth import resolve_token

    caps = dict(client_capabilities or {})
    token = resolve_token(config, transport=transport, request_headers=request_headers)
    return ToolContext(
        config=config,
        client=client,
        catalog=catalog,
        transport=transport,
        tool_name=tool_name,
        token=token,
        client_capabilities=caps,
        elicitation_supported="elicitation" in caps,
        elicited=elicited,
        request_id=request_id,
        stats=stats if stats is not None else UpstreamStats(),
        log=structlog.get_logger("neon_mcp.tool").bind(tool=tool_name, request_id=request_id),
    )
