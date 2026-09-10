"""NEON API token model, resolution and placement rules.

Since NEON Data API 0.11.0 (June 2026) the data-file, data-query and sample
view/download endpoints answer 403 without an ``X-API-Token`` header; every
other endpoint is anonymous. A :class:`Token` never prints its value, and
every token the process sees is registered with the log redactor.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog

from neon_mcp.errors import API_TOKEN_GUIDE, AUTH_REQUIRED_MESSAGE, ToolError
from neon_mcp.logging import register_secret

if TYPE_CHECKING:
    from neon_mcp.config import Config
    from neon_mcp.context import ToolContext

log = structlog.get_logger("neon_mcp.auth")

TOKEN_ENDPOINT_PREFIXES: tuple[str, ...] = ("/data/", "/samples/view", "/samples/download")
TOKEN_ENDPOINT_RE = re.compile(r"^/releases/[^/]+/data/")
TOKEN_HEADER = "X-API-Token"

_warned_insecure_header = False


@dataclass(frozen=True, repr=False)
class Token:
    """A NEON API token. ``repr``/``str`` never reveal the value."""

    value: str = field(repr=False)
    source: Literal["config", "request"]

    def __post_init__(self) -> None:
        register_secret(self.value)

    def identity(self) -> str:
        """Stable non-reversible key for caches and rate buckets."""
        return "tok:" + hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:12]

    def __repr__(self) -> str:
        return f"Token(<redacted>, source={self.source!r})"

    __str__ = __repr__


def is_token_endpoint(path: str) -> bool:
    """True for API paths (relative to the base URL) that require a token."""
    return path.startswith(TOKEN_ENDPOINT_PREFIXES) or bool(TOKEN_ENDPOINT_RE.match(path))


def header_token_allowed(config: Config) -> bool:
    """Per-request header tokens need TLS in front (or an explicit dev override)."""
    base = config.server.public_base_url or ""
    return base.lower().startswith("https://") or config.server.allow_insecure_header_token


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def resolve_token(
    config: Config,
    *,
    transport: Literal["stdio", "http"],
    request_headers: Mapping[str, str] | None,
) -> Token | None:
    """Pick the token for one call (DESIGN.md 3.2).

    stdio: the configured token. http: the caller's header token when accepted
    and the TLS gate allows it; else the configured token only when the
    operator opted into sharing it; else ``None``.
    """
    global _warned_insecure_header
    configured = config.token_value()
    if transport == "stdio":
        return Token(configured, "config") if configured else None

    if request_headers and config.server.accept_header_token:
        raw = _header(request_headers, config.server.request_token_header)
        value = raw.strip() if raw else ""
        if value:
            if header_token_allowed(config):
                return Token(value, "request")
            if not _warned_insecure_header:
                _warned_insecure_header = True
                log.warning(
                    "auth.header_token_ignored",
                    reason="public_base_url is not https:// and allow_insecure_header_token is false",
                )
    if configured and config.server.share_config_token_over_http:
        return Token(configured, "config")
    return None


def require_token(ctx: ToolContext, *, endpoint: str) -> Token:
    """Return the call's token or fail with ``auth_required`` before any request."""
    if ctx.token is None:
        raise ToolError(
            "auth_required",
            AUTH_REQUIRED_MESSAGE,
            details={"guide": API_TOKEN_GUIDE, "endpoint": endpoint, "tokenSource": "none"},
            hint="Read neon://guide/api-token.",
        )
    return ctx.token


def _reset_warning_for_tests() -> None:
    global _warned_insecure_header
    _warned_insecure_header = False
