"""The tool registry: declaration, validation, invocation and size budgets.

Tools register at import time with :func:`register_tool`. The registry is
independent of the MCP SDK: :func:`invoke` validates arguments against the
tool's pydantic input model, fails fast with ``auth_required`` for token
tools when no token is available, runs the handler, dumps the output model
(camelCase, ``None`` omitted), stamps a default ``source`` and enforces the
result-size budget with :func:`fit_to_budget`.

MRTR continuations (``requestState``) are encoded here: compact JSON,
base64url, at most 16 KiB, never containing token/authorization keys, and
rejected on resume when malformed, for another tool, or older than an hour.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from neon_mcp.errors import (
    API_TOKEN_GUIDE,
    AUTH_REQUIRED_MESSAGE,
    NeonApiError,
    ToolError,
    map_api_error,
)
from neon_mcp.logging import registered_secrets
from neon_mcp.models.common import NeonInput, ToolResultBase

if TYPE_CHECKING:
    from neon_mcp.context import ToolContext, UpstreamStats

Surface = Literal[
    "core",
    "catalog",
    "locations",
    "data",
    "releases",
    "taxonomy",
    "samples",
    "prototype",
    "documents",
    "graphql",
]
SURFACES: tuple[str, ...] = (
    "core",
    "catalog",
    "locations",
    "data",
    "releases",
    "taxonomy",
    "samples",
    "prototype",
    "documents",
    "graphql",
)
ToolHandler = Callable[[Any, "ToolContext"], Awaitable[ToolResultBase]]

NAME_RE = re.compile(r"^neon_[a-z_]+$")
NEXT_SENTENCE_RE = re.compile(r"(?:^|[.!?)]\s+)Next: [^\n]+$")
MAX_DESCRIPTION_CHARS = 600
MAX_REQUEST_STATE_BYTES = 16 * 1024
REQUEST_STATE_MAX_AGE_S = 3600.0
REQUEST_STATE_VERSION = 1
_FORBIDDEN_STATE_KEY = re.compile(r"(?i)token|authorization")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    handler: ToolHandler
    input_model: type[NeonInput]
    output_model: type[ToolResultBase]
    surface: Surface
    requires_token: bool
    token_check: Literal["registry", "handler"]
    endpoints: tuple[str, ...]
    transports: frozenset[str]
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool
    supports_mrtr: bool
    needs_downloads: bool


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    *,
    title: str,
    description: str,
    input_model: type[NeonInput],
    output_model: type[ToolResultBase],
    surface: Surface,
    endpoints: Sequence[str],
    requires_token: bool = False,
    token_check: Literal["registry", "handler"] = "registry",
    transports: Iterable[str] = ("stdio", "http"),
    read_only: bool = True,
    destructive: bool = False,
    idempotent: bool = True,
    open_world: bool = True,
    supports_mrtr: bool = False,
    needs_downloads: bool = False,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator adding a tool to the registry; validates the declaration."""
    if not NAME_RE.match(name):
        raise ValueError(f"tool name {name!r} must match {NAME_RE.pattern}")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ValueError(
            f"{name}: description is {len(description)} chars (max {MAX_DESCRIPTION_CHARS})"
        )
    if not NEXT_SENTENCE_RE.search(description):
        raise ValueError(f"{name}: description must end with a sentence starting 'Next:'")
    if not (isinstance(input_model, type) and issubclass(input_model, NeonInput)):
        raise TypeError(f"{name}: input_model must subclass NeonInput")
    if not (isinstance(output_model, type) and issubclass(output_model, ToolResultBase)):
        raise TypeError(f"{name}: output_model must subclass ToolResultBase")
    if surface not in SURFACES:
        raise ValueError(f"{name}: unknown surface {surface!r}")

    def decorator(handler: ToolHandler) -> ToolHandler:
        if name in _REGISTRY:
            raise ValueError(f"Tool {name!r} already registered")
        _REGISTRY[name] = ToolSpec(
            name=name,
            title=title,
            description=description,
            handler=handler,
            input_model=input_model,
            output_model=output_model,
            surface=surface,
            requires_token=requires_token,
            token_check=token_check,
            endpoints=tuple(endpoints),
            transports=frozenset(transports),
            read_only=read_only,
            destructive=destructive,
            idempotent=idempotent,
            open_world=open_world,
            supports_mrtr=supports_mrtr,
            needs_downloads=needs_downloads,
        )
        return handler

    return decorator


def get_registered_tools(
    *, transport: str | None = None, downloads_enabled: bool = True
) -> list[ToolSpec]:
    """Registered tools sorted by name, filtered for one deployment."""
    specs = sorted(_REGISTRY.values(), key=lambda s: s.name)
    if transport is not None:
        specs = [s for s in specs if transport in s.transports]
    if not downloads_enabled:
        specs = [s for s in specs if not s.needs_downloads]
    return specs


def get_tool(name: str) -> ToolSpec:
    """Look up a tool; ``KeyError`` when unknown."""
    return _REGISTRY[name]


def unregister_tool(name: str) -> None:
    """Test helper: remove one tool."""
    _REGISTRY.pop(name, None)


def clear_registry() -> None:
    """Test helper: remove every tool."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def format_validation_error(exc: ValidationError, spec: ToolSpec) -> ToolError:
    """Turn a pydantic error into an actionable ``invalid_argument``."""
    errors = exc.errors(include_url=False, include_input=False)
    first = errors[0] if errors else {"loc": (), "msg": str(exc), "type": "value_error"}
    loc = ".".join(str(p) for p in first.get("loc", ())) or "arguments"
    valid = sorted(spec.input_model.model_fields)
    if first.get("type") == "extra_forbidden":
        message = f"Unknown argument {loc!r} for {spec.name}. Valid arguments: {', '.join(valid)}."
    else:
        message = f"Invalid argument {loc!r} for {spec.name}: {first.get('msg')}"
    return ToolError(
        "invalid_argument",
        message,
        details={
            "tool": spec.name,
            "errors": [
                {
                    "loc": [str(p) for p in e.get("loc", ())],
                    "msg": e.get("msg"),
                    "type": e.get("type"),
                }
                for e in errors[:10]
            ],
        },
    )


def default_source(stats: UpstreamStats) -> dict[str, Any]:
    endpoints = list(stats.endpoints)
    if not endpoints:
        via = "local"
    elif all(e == "POST /graphql" for e in endpoints):
        via = "graphql"
    elif "POST /graphql" in endpoints:
        via = "mixed"
    else:
        via = "rest"
    return {
        "endpoints": endpoints,
        "via": via,
        "cached": stats.requests == 0 and stats.cache_hits > 0,
        "derived": [],
    }


async def invoke(
    spec: ToolSpec, raw_args: Mapping[str, Any] | None, ctx: ToolContext
) -> dict[str, Any]:
    """Validate, authorize, run and shape one tool call."""
    try:
        args = spec.input_model.model_validate(dict(raw_args or {}))
    except ValidationError as exc:
        raise format_validation_error(exc, spec) from None

    if spec.requires_token and spec.token_check == "registry" and ctx.token is None:
        raise ToolError(
            "auth_required",
            AUTH_REQUIRED_MESSAGE,
            details={"guide": API_TOKEN_GUIDE, "tool": spec.name, "tokenSource": "none"},
            hint="Read neon://guide/api-token; discovery and availability tools work without a token.",
        )

    try:
        result = await spec.handler(args, ctx)
    except NeonApiError as exc:
        raise map_api_error(
            exc, requires_token=spec.requires_token, secrets=registered_secrets()
        ) from None

    if not isinstance(result, spec.output_model):
        raise ToolError(
            "internal_error",
            f"Tool {spec.name!r} returned {type(result).__name__}, expected {spec.output_model.__name__}.",
        )
    payload = result.model_dump(by_alias=True, exclude_none=True, mode="json")
    if "source" not in payload:
        payload["source"] = default_source(ctx.stats)
    limits = ctx.config.limits
    payload = fit_to_budget(payload, spec.output_model, limits.max_result_bytes)
    size = json_size(payload)
    if size > limits.hard_max_result_bytes:
        raise ToolError(
            "result_too_large",
            f"The result is {size} bytes, above the {limits.hard_max_result_bytes}-byte hard limit.",
            details={"bytes": size, "limit": limits.hard_max_result_bytes},
            hint="Narrow the request (fewer sites/months, smaller limit, fewer include sections).",
        )
    return payload


def json_size(obj: Any) -> int:
    """Size of the compact JSON encoding in bytes (what goes on the wire)."""
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _wire_name(model: type[ToolResultBase], field: str) -> str:
    info = model.model_fields.get(field)
    if info is not None and info.alias:
        return info.alias
    alias_gen = model.model_config.get("alias_generator")
    if callable(alias_gen):
        return str(alias_gen(field))
    return field


def _mark_trimmed(
    payload: dict[str, Any],
    output_model: type[ToolResultBase],
    kept: int,
    max_bytes: int,
    note_index: int | None,
) -> int | None:
    """Rewrite the budget list's Page and add (or refresh) the trimming note."""
    page = payload.get(_wire_name(output_model, output_model.budget_page))
    next_offset = kept
    if isinstance(page, dict):
        next_offset = int(page.get("offset", 0)) + kept
        page.update(returned=kept, truncated=True, nextOffset=next_offset, truncatedReason="budget")
    steps = payload.setdefault("nextSteps", [])
    if not isinstance(steps, list):
        return note_index
    note = (
        f"Result trimmed to fit {max_bytes} bytes; call again with offset={next_offset} "
        "or a smaller limit."
    )
    if note_index is None:
        steps.append(note)
        return len(steps) - 1
    steps[note_index] = note
    return note_index


def fit_to_budget(
    payload: dict[str, Any], output_model: type[ToolResultBase], max_bytes: int
) -> dict[str, Any]:
    """Trim ``output_model.budget_list`` (eliding URL-like fields first) to fit ``max_bytes``."""
    size = json_size(payload)
    if size <= max_bytes or not output_model.budget_list:
        return payload
    key = _wire_name(output_model, output_model.budget_list)
    items = payload.get(key)
    if not isinstance(items, list) or not items:
        return payload

    elided = False
    for item in reversed(items):
        if size <= max_bytes:
            break
        if not isinstance(item, dict):
            continue
        for field in output_model.budget_elide_fields:
            if item.get(field) is not None:
                size -= json_size(item[field]) - 4  # "null"
                item[field] = None
                elided = True
    if elided and output_model.budget_elide_flag:
        payload[_wire_name(output_model, output_model.budget_elide_flag)] = True
    size = json_size(payload)

    note_index: int | None = None
    while items and size > max_bytes:
        excess = size - max_bytes
        removed = 0
        while items and removed < excess:
            removed += json_size(items.pop()) + 1
        note_index = _mark_trimmed(payload, output_model, len(items), max_bytes, note_index)
        size = json_size(payload)
    return payload


# ---------------------------------------------------------------------------
# MRTR request state
# ---------------------------------------------------------------------------


def _forbidden_keys(obj: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            dotted = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and _FORBIDDEN_STATE_KEY.search(key):
                found.append(dotted)
            found.extend(_forbidden_keys(value, dotted))
    elif isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            found.extend(_forbidden_keys(value, f"{path}[{idx}]"))
    return found


def encode_request_state(state: Mapping[str, Any]) -> str:
    """Serialize an MRTR continuation (deliberately unsigned; see DESIGN.md 7.2)."""
    bad = _forbidden_keys(state)
    if bad:
        raise ToolError(
            "internal_error",
            "Refusing to put credential-like keys in requestState.",
            details={"keys": bad},
        )
    raw = json.dumps(dict(state), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_REQUEST_STATE_BYTES:
        raise ToolError(
            "internal_error",
            "MRTR continuation state is too large to round-trip.",
            details={"bytes": len(raw), "limit": MAX_REQUEST_STATE_BYTES},
        )
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_request_state(
    encoded: str, *, expected_tool: str, now: float | None = None
) -> dict[str, Any]:
    """Decode an untrusted continuation; ``invalid_argument`` on any problem."""
    if not isinstance(encoded, str) or len(encoded) > MAX_REQUEST_STATE_BYTES * 2:
        raise ToolError("invalid_argument", "requestState is too large or not a string.")
    try:
        decoded = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError):
        raise ToolError("invalid_argument", "requestState is not a valid continuation.") from None
    if not isinstance(decoded, dict):
        raise ToolError("invalid_argument", "requestState must decode to an object.")
    if decoded.get("v") != REQUEST_STATE_VERSION:
        raise ToolError("invalid_argument", "requestState has an unsupported version.")
    if decoded.get("tool") != expected_tool:
        raise ToolError(
            "invalid_argument",
            "requestState belongs to a different tool.",
            details={"expectedTool": expected_tool},
        )
    issued = decoded.get("issuedAt")
    current = time.time() if now is None else now
    if not isinstance(issued, (int, float)) or issued > current + 300:
        raise ToolError("invalid_argument", "requestState has an invalid issue time.")
    if current - issued > REQUEST_STATE_MAX_AGE_S:
        raise ToolError(
            "invalid_argument", "continuation expired; call the tool again without requestState."
        )
    return decoded
