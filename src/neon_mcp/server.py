"""The MCP adapter: exposes the tool registry, resources and prompts over the SDK.

Targets the **MCP 2026-07-28** stateless core via the low-level
``mcp.server.Server`` (SDK 2.x constructor callbacks). The registry stays
SDK-agnostic; this module is the only SDK-coupled seam:

* ``tools/list`` is sorted, fixed per deployment (transport + downloads), and
  carries a public cache hint; every schema declares JSON Schema 2020-12.
* ``tools/call`` results carry compact JSON as text *and* ``structuredContent``
  plus ``io.neon-mcp/upstream`` ``_meta`` (the SDK adds ``serverInfo``).
* A handler's :class:`~neon_mcp.errors.InputRequired` becomes an MRTR
  ``InputRequiredResult``; its continuation travels as ``requestState``.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog
from mcp import types as t

from neon_mcp import __version__
from neon_mcp.config import Config
from neon_mcp.context import (
    Elicited,
    UpstreamStats,
    build_tool_context,
    current_request_headers,
    current_request_id,
)
from neon_mcp.errors import InputRequired, ToolError
from neon_mcp.registry import (
    REQUEST_STATE_VERSION,
    ToolSpec,
    decode_request_state,
    encode_request_state,
    get_registered_tools,
    get_tool,
    invoke,
)

if TYPE_CHECKING:
    import httpx
    from mcp.server import Server

    from neon_mcp.context import ToolContext
    from neon_mcp.neon.catalog import Catalog
    from neon_mcp.neon.client import NeonClient

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
TOOLS_LIST_TTL_MS = 300_000
RESOURCES_LIST_TTL_MS = 3_600_000
RESOURCE_READ_STATIC_TTL_MS = 86_400_000
RESOURCE_READ_DERIVED_TTL_MS = 3_600_000
PROMPTS_LIST_TTL_MS = 86_400_000
DISCOVER_TTL_MS = 300_000

META_SURFACE = "io.neon-mcp/surface"
META_REQUIRES_TOKEN = "io.neon-mcp/requiresToken"
META_ENDPOINTS = "io.neon-mcp/endpoints"
META_STDIO_ONLY = "io.neon-mcp/stdioOnly"
META_UPSTREAM = "io.neon-mcp/upstream"
META_RESOURCE_KIND = "io.neon-mcp/kind"

SERVER_DESCRIPTION = (
    "Discover, check availability for, list/download files of, and cite NEON "
    "(National Ecological Observatory Network) data."
)

log = structlog.get_logger("neon_mcp.server")


@dataclass
class CallOutcome:
    payload: dict[str, Any]
    is_error: bool
    input_required: InputRequired | None
    stats: UpstreamStats
    request_state: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def compact_schema(schema: Any, keywords: tuple[str, ...]) -> Any:
    """Drop annotation keywords (string-valued only, so a property *named* ``title`` survives)."""
    if isinstance(schema, dict):
        return {
            k: compact_schema(v, keywords)
            for k, v in schema.items()
            if not (k in keywords and isinstance(v, str))
        }
    if isinstance(schema, list):
        return [compact_schema(v, keywords) for v in schema]
    return schema


def _plain_responses(responses: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """MRTR answers arrive as SDK models (``ElicitResult``); handlers get plain JSON."""
    if not responses:
        return None
    out: dict[str, Any] = {}
    for key, value in responses.items():
        dump = getattr(value, "model_dump", None)
        out[key] = dump(by_alias=True, exclude_none=True, mode="json") if callable(dump) else value
    return out


class NeonServer:
    """Process-wide server object; one per transport deployment."""

    def __init__(
        self,
        config: Config,
        *,
        transport: Literal["stdio", "http"],
        client: NeonClient,
        catalog: Catalog,
    ) -> None:
        self.config = config
        self.transport: Literal["stdio", "http"] = transport
        self.client = client
        self.catalog = catalog
        #: ``warming`` while an HTTP prewarm runs, ``degraded`` if it failed.
        self.readiness: Literal["ready", "warming", "degraded"] = "ready"

    # ------------------------------------------------------------------ tools

    @property
    def downloads_enabled(self) -> bool:
        return self.config.effective_downloads_enabled(self.transport)

    @property
    def tools(self) -> list[ToolSpec]:
        return get_registered_tools(
            transport=self.transport, downloads_enabled=self.downloads_enabled
        )

    @staticmethod
    def input_schema(spec: ToolSpec) -> dict[str, Any]:
        """Validation schema by alias; pydantic's auto titles dropped, descriptions kept for the model."""
        raw = spec.input_model.model_json_schema(by_alias=True, mode="validation")
        schema: dict[str, Any] = dict(compact_schema(raw, ("title",)))
        schema["$schema"] = JSON_SCHEMA_DIALECT
        return schema

    @staticmethod
    def output_schema(spec: ToolSpec) -> dict[str, Any]:
        """Serialization schema by alias, without titles/descriptions (docs render them from the models)."""
        raw = spec.output_model.model_json_schema(by_alias=True, mode="serialization")
        schema: dict[str, Any] = dict(compact_schema(raw, ("title", "description")))
        schema["$schema"] = JSON_SCHEMA_DIALECT
        return schema

    def tool_definitions(self) -> list[t.Tool]:
        out: list[t.Tool] = []
        for spec in self.tools:
            meta: dict[str, Any] = {
                META_SURFACE: spec.surface,
                META_REQUIRES_TOKEN: spec.requires_token,
                META_ENDPOINTS: list(spec.endpoints),
            }
            if "http" not in spec.transports:
                meta[META_STDIO_ONLY] = True
            out.append(
                t.Tool(
                    name=spec.name,
                    title=spec.title,
                    description=spec.description,
                    input_schema=self.input_schema(spec),
                    output_schema=self.output_schema(spec),
                    annotations=t.ToolAnnotations(
                        title=spec.title,
                        read_only_hint=spec.read_only,
                        destructive_hint=spec.destructive,
                        idempotent_hint=spec.idempotent,
                        open_world_hint=spec.open_world,
                    ),
                    meta=meta,
                )
            )
        return out

    def tool_context(
        self,
        tool_name: str,
        *,
        client_capabilities: Mapping[str, Any] | None = None,
        elicited: Elicited | None = None,
        request_id: str | None = None,
        request_headers: Mapping[str, str] | None = None,
        stats: UpstreamStats | None = None,
    ) -> ToolContext:
        return build_tool_context(
            config=self.config,
            client=self.client,
            catalog=self.catalog,
            transport=self.transport,
            tool_name=tool_name,
            client_capabilities=client_capabilities,
            elicited=elicited,
            request_id=request_id,
            request_headers=request_headers,
            stats=stats,
        )

    async def call(
        self,
        name: str,
        args: Mapping[str, Any] | None = None,
        *,
        input_responses: Mapping[str, Any] | None = None,
        request_state: str | None = None,
        request_headers: Mapping[str, str] | None = None,
        client_capabilities: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> CallOutcome:
        """Run one tool call in-process (the adapter, tests and ``--check`` use this)."""
        stats = UpstreamStats()
        started = time.monotonic()
        outcome: CallOutcome
        try:
            spec = get_tool(name)
        except KeyError:
            err = ToolError(
                "unknown_tool",
                f"No tool named {name!r}.",
                details={"name": name, "available": [s.name for s in self.tools]},
            )
            return CallOutcome(err.to_payload(), True, None, stats)
        try:
            elicited = None
            if input_responses:
                state = decode_request_state(request_state or "", expected_tool=name)
                elicited = Elicited(responses=dict(input_responses), state=state)
            ctx = self.tool_context(
                name,
                client_capabilities=client_capabilities,
                elicited=elicited,
                request_id=request_id,
                request_headers=request_headers,
                stats=stats,
            )
            payload = await invoke(spec, args, ctx)
            outcome = CallOutcome(payload, False, None, stats)
        except InputRequired as pending:
            state = {
                "v": REQUEST_STATE_VERSION,
                "tool": name,
                "issuedAt": time.time(),
                **pending.state,
            }
            outcome = CallOutcome(
                {}, False, pending, stats, request_state=encode_request_state(state)
            )
        except ToolError as exc:
            outcome = CallOutcome(exc.to_payload(), True, None, stats)
        except Exception:
            log.exception("tool.crash", tool=name, request_id=request_id)
            err = ToolError(
                "internal_error",
                "The tool failed unexpectedly; the error was logged on the server.",
                details={"correlationId": request_id},
            )
            outcome = CallOutcome(err.to_payload(), True, None, stats)
        log.info(
            "tool.call",
            tool=name,
            ms=round((time.monotonic() - started) * 1000, 1),
            ok=not outcome.is_error,
            code=(outcome.payload.get("error") or {}).get("code") if outcome.is_error else None,
            result_bytes=len(_dumps(outcome.payload)),
            upstream_requests=stats.requests,
            cache_hits=stats.cache_hits,
            request_id=request_id,
        )
        return outcome

    # ------------------------------------------------------------------ MCP

    def build_mcp_server(self) -> Server[Any]:
        from mcp.server import Server
        from mcp.server.caching import CacheHint
        from mcp.shared.exceptions import MCPError

        from neon_mcp import prompts as prompt_mod
        from neon_mcp import resources as resource_mod
        from neon_mcp.instructions import SERVER_INSTRUCTIONS

        async def _on_list_tools(_ctx: Any, _params: Any = None) -> t.ListToolsResult:
            return t.ListToolsResult(tools=self.tool_definitions())

        async def _on_call_tool(
            ctx: Any, params: t.CallToolRequestParams
        ) -> t.CallToolResult | t.InputRequiredResult:
            meta = ctx.meta if isinstance(ctx.meta, Mapping) else {}
            caps = meta.get(t.CLIENT_CAPABILITIES_META_KEY)
            headers = current_request_headers.get()
            if headers is None and getattr(ctx, "request", None) is not None:
                headers = getattr(ctx.request, "headers", None)
            request_id = current_request_id.get() or (
                str(ctx.request_id) if ctx.request_id is not None else None
            )
            outcome = await self.call(
                params.name,
                params.arguments,
                input_responses=_plain_responses(params.input_responses),
                request_state=params.request_state,
                request_headers=headers,
                client_capabilities=caps if isinstance(caps, Mapping) else None,
                request_id=request_id,
            )
            if outcome.input_required is not None:
                pending = outcome.input_required
                return t.InputRequiredResult(
                    input_requests={
                        pending.key: t.ElicitRequest(
                            method="elicitation/create",
                            params=t.ElicitRequestFormParams(
                                mode="form",
                                message=pending.message,
                                requested_schema=pending.requested_schema,
                            ),
                        )
                    },
                    request_state=outcome.request_state,
                )
            return t.CallToolResult(
                content=[t.TextContent(type="text", text=_dumps(outcome.payload))],
                structured_content=outcome.payload,
                is_error=outcome.is_error,
                meta={META_UPSTREAM: outcome.stats.as_meta()},
            )

        async def _on_list_resources(_ctx: Any, _params: Any = None) -> t.ListResourcesResult:
            return t.ListResourcesResult(resources=resource_mod.list_resources())

        async def _on_list_resource_templates(
            _ctx: Any, _params: Any = None
        ) -> t.ListResourceTemplatesResult:
            return t.ListResourceTemplatesResult(
                resource_templates=resource_mod.list_resource_templates()
            )

        async def _on_read_resource(
            ctx: Any, params: t.ReadResourceRequestParams
        ) -> t.ReadResourceResult:
            uri = str(params.uri)
            tool_ctx = self.tool_context(
                "resources/read", request_headers=current_request_headers.get()
            )
            try:
                content = await resource_mod.read_resource(uri, tool_ctx, server=self)
            except ToolError as exc:
                raise MCPError(
                    t.INVALID_PARAMS,
                    exc.message,
                    data={
                        "code": exc.code,
                        **{k: v for k, v in exc.details.items() if k in ("didYouMean", "uri")},
                    },
                ) from None
            return t.ReadResourceResult(
                contents=[
                    t.TextResourceContents(uri=uri, text=content.text, mime_type=content.mime_type)
                ],
                ttl_ms=content.ttl_ms,
                cache_scope="public",
            )

        async def _on_list_prompts(_ctx: Any, _params: Any = None) -> t.ListPromptsResult:
            return t.ListPromptsResult(prompts=prompt_mod.list_prompts())

        async def _on_get_prompt(_ctx: Any, params: t.GetPromptRequestParams) -> t.GetPromptResult:
            try:
                return prompt_mod.get_prompt(params.name, params.arguments)
            except ToolError as exc:
                raise MCPError(t.INVALID_PARAMS, exc.message, data={"code": exc.code}) from None

        instructions = SERVER_INSTRUCTIONS
        if self.config.server.instructions_extra:
            instructions += "\n\n" + self.config.server.instructions_extra
        return Server(
            "neon-mcp",
            version=__version__,
            title="NEON Data API",
            description=SERVER_DESCRIPTION,
            instructions=instructions,
            website_url="https://github.com/idss-mesa/neon-mcp",
            cache_hints={
                "tools/list": CacheHint(
                    ttl_ms=self.config.server.tools_list_ttl_ms, scope="public"
                ),
                "resources/list": CacheHint(ttl_ms=RESOURCES_LIST_TTL_MS, scope="public"),
                "resources/templates/list": CacheHint(ttl_ms=RESOURCES_LIST_TTL_MS, scope="public"),
                "resources/read": CacheHint(ttl_ms=RESOURCE_READ_DERIVED_TTL_MS, scope="public"),
                "prompts/list": CacheHint(ttl_ms=PROMPTS_LIST_TTL_MS, scope="public"),
                "server/discover": CacheHint(ttl_ms=DISCOVER_TTL_MS, scope="public"),
            },
            on_list_tools=_on_list_tools,
            on_call_tool=_on_call_tool,
            on_list_resources=_on_list_resources,
            on_list_resource_templates=_on_list_resource_templates,
            on_read_resource=_on_read_resource,
            on_list_prompts=_on_list_prompts,
            on_get_prompt=_on_get_prompt,
        )

    async def serve(self) -> None:
        if self.transport == "stdio":
            from neon_mcp.transport.stdio import serve_stdio

            await serve_stdio(self)
        else:
            from neon_mcp.transport.streamable_http import serve_http

            await serve_http(self)

    async def aclose(self) -> None:
        await self.client.aclose()


def create_server(
    config: Config,
    *,
    transport: Literal["stdio", "http"] | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> NeonServer:
    """Wire cache, rate limiter, client and catalog; import every tool module."""
    from neon_mcp import tools as _tools  # noqa: F401  (registration side effect)
    from neon_mcp.neon.cache import TTLCache
    from neon_mcp.neon.catalog import Catalog
    from neon_mcp.neon.client import NeonClient
    from neon_mcp.neon.ratelimit import RateLimiter

    mode: Literal["stdio", "http"] = transport or config.server.transport
    sleeper = sleep or asyncio.sleep
    cache = TTLCache(config.cache)
    limiter = RateLimiter(
        config.neon.rate_limit, max_concurrency=config.neon.max_concurrency, sleep=sleeper
    )
    client = NeonClient(
        config.neon,
        cache=cache,
        limiter=limiter,
        send_token_on_public=config.effective_token_for_public(mode),
        transport=http_transport,
        sleep=sleeper,
        allowed_hosts=config.downloads.allowed_hosts,
    )
    catalog = Catalog(client, cache, config)
    return NeonServer(config, transport=mode, client=client, catalog=catalog)


def run(config: Config, transport: str | None = None) -> None:
    """Blocking entry point used by the CLI."""
    import anyio

    mode: Literal["stdio", "http"] = (
        "http" if (transport or config.server.transport) == "http" else "stdio"
    )
    server = create_server(config, transport=mode)
    anyio.run(server.serve)
