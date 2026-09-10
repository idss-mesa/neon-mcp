"""Configuration model and loader for neon-mcp.

Precedence (highest wins): CLI flag > environment variable > YAML file > default.

Environment variables use the ``NEON_MCP_`` prefix and ``__`` to descend into
nested sections at any depth: ``NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_RPS``
sets ``config.neon.rate_limit.anonymous_rps``. List fields accept a
comma-separated string. The NEON API token (``NEON_MCP_NEON__API_TOKEN``)
additionally falls back to ``NEON_TOKEN`` (the variable neonUtilities
documents) and then ``NEON_API_TOKEN``.

The loader validates shape only; it never contacts NEON.
"""

from __future__ import annotations

import logging
import os
import types as _pytypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

logger = logging.getLogger(__name__)

Transport = Literal["stdio", "http"]
LogLevel = Literal["debug", "info", "warning", "error", "critical"]

ENV_PREFIX = "NEON_MCP_"
ENV_DELIM = "__"
#: Token variables consulted, in order, when NEON_MCP_NEON__API_TOKEN is unset.
TOKEN_ENV_FALLBACKS: tuple[str, ...] = ("NEON_TOKEN", "NEON_API_TOKEN")


class _Section(BaseModel):
    # Unknown keys are warned about by the loader, not rejected: failing to
    # start over a stale key is worse than running with a documented default.
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class RateLimitConfig(_Section):
    """Client-side token buckets, kept 10 % under NEON's published limits."""

    anonymous_burst: int = Field(
        180, ge=1, description="Burst size for anonymous requests (NEON: 200 per IP)."
    )
    anonymous_rps: float = Field(
        1.8, gt=0, description="Sustained requests/second without a token (NEON: 2)."
    )
    token_burst: int = Field(
        1800, ge=1, description="Burst size for requests carrying a token (NEON: 2000)."
    )
    token_rps: float = Field(
        7.2, gt=0, description="Sustained requests/second with a token (NEON: 8)."
    )
    low_water: int = Field(
        5, ge=0, description="When X-RateLimit-Remaining falls to this value, wait for the reset."
    )
    max_wait_s: float = Field(
        10.0,
        ge=0,
        description="Longest the client sleeps for rate-limit headroom before failing with rate_limited.",
    )


class RetryConfig(_Section):
    """Retry policy for 429, 5xx and network failures (all NEON calls are idempotent)."""

    max_attempts: int = Field(
        3, ge=1, le=10, description="Attempts per upstream call, including the first."
    )
    backoff_base_s: float = Field(
        0.5, ge=0, description="Base of the exponential backoff (0.5 * 2^n seconds)."
    )
    backoff_max_s: float = Field(8.0, ge=0, description="Cap on a single backoff sleep.")
    retry_after_default_s: float = Field(
        1.0, ge=0, description="Wait used on HTTP 429 when NEON sends no RetryAfter header."
    )


class NeonConfig(_Section):
    """Upstream NEON Data API settings."""

    base_url: str = Field(
        "https://data.neonscience.org/api/v0", description="NEON REST API base URL."
    )
    graphql_url: str = Field(
        "https://data.neonscience.org/graphql",
        description="NEON GraphQL endpoint (not under /api/v0).",
    )
    api_token: SecretStr | None = Field(
        None,
        description="NEON API token (https://data.neonscience.org/myaccount). Required for data files, "
        "data queries and sample views. Prefer the env var; never commit it. Fallbacks: NEON_TOKEN, NEON_API_TOKEN.",
    )
    token_for_public_endpoints: bool | None = Field(
        None,
        description="Also send the token to public endpoints (raises the rate limit). "
        "Unset: true on stdio, false on http.",
    )
    user_agent_suffix: str | None = Field(
        None, description="Text appended to the User-Agent header."
    )
    connect_timeout_s: float = Field(10.0, gt=0, description="TCP/TLS connect timeout.")
    read_timeout_s: float = Field(60.0, gt=0, description="Default read timeout.")
    catalog_read_timeout_s: float = Field(
        180.0, gt=0, description="Read timeout for catalog-sized fetches (product/site lists)."
    )
    download_read_timeout_s: float = Field(
        300.0, gt=0, description="Read timeout for file downloads."
    )
    max_concurrency: int = Field(
        4, ge=1, le=32, description="Maximum simultaneous upstream requests."
    )
    prefer_graphql: bool = Field(
        True, description="Build catalogs and availability from GraphQL (REST is the fallback)."
    )
    graphql_breaker_failures: int = Field(
        2, ge=1, description="Consecutive GraphQL failures that open the circuit breaker."
    )
    graphql_breaker_cooldown_s: float = Field(
        900.0, ge=0, description="How long an open GraphQL breaker routes everything to REST."
    )
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retries: RetryConfig = Field(default_factory=RetryConfig)


class CacheTTLs(_Section):
    """Time-to-live, in seconds, per cache family."""

    catalog: int = Field(
        3600,
        ge=0,
        description="Product/site catalogs, releases list, prototype list, site locations.",
    )
    detail: int = Field(
        900, ge=0, description="Single product/site/release detail and GraphQL availability."
    )
    locations: int = Field(21600, ge=0, description="Location records and hierarchies.")
    releases: int = Field(21600, ge=0, description="Release records.")
    taxonomy: int = Field(86400, ge=0, description="Taxonomy pages.")
    samples_classes: int = Field(86400, ge=0, description="Sample-class lists.")
    samples_view: int = Field(60, ge=0, description="Sample views (token-scoped).")
    data: int = Field(600, ge=0, description="Data-file listings (signed URLs live 7 days).")
    prototype: int = Field(21600, ge=0, description="Prototype dataset records.")
    documents: int = Field(86400, ge=0, description="Document metadata and extracted text.")


class CacheConfig(_Section):
    """In-process response cache."""

    enabled: bool = Field(True, description="Cache upstream responses in memory.")
    max_entries: int = Field(1024, ge=1, description="Overall entry cap across families.")
    max_index_entries: int = Field(
        4, ge=1, description="Cap on built catalog index objects (one per release)."
    )
    prewarm: bool | None = Field(
        None, description="Build the catalogs at startup. Unset: true on http, false on stdio."
    )
    refresh_ahead: float = Field(
        0.1,
        ge=0,
        le=1,
        description="Fraction of a TTL before expiry at which http mode refreshes in the background.",
    )
    stale_if_error_s: int = Field(
        86400, ge=0, description="How long an expired entry may be served when a refresh fails."
    )
    ttl_s: CacheTTLs = Field(default_factory=CacheTTLs)


class LimitsConfig(_Section):
    """Result-size and request-shape limits."""

    default_limit: int = Field(
        50, ge=1, description="Default page size where a tool does not set its own."
    )
    max_limit: int = Field(500, ge=1, description="Largest page size any tool accepts.")
    max_result_bytes: int = Field(
        50_000,
        ge=1000,
        description="Tool results are trimmed (with page.truncated) to fit this many bytes of compact JSON.",
    )
    hard_max_result_bytes: int = Field(
        200_000,
        ge=1000,
        description="A result still larger than this after trimming fails with result_too_large.",
    )
    text_budget_summary: int = Field(
        300, ge=40, description="Characters kept of long text fields in summaries."
    )
    text_budget_detail: int = Field(
        4000, ge=100, description="Default characters kept of long text fields in detail views."
    )
    max_sites_per_call: int = Field(
        30, ge=1, description="Most sites one neon_list_files / neon_download_files call accepts."
    )
    max_site_months_per_query: int = Field(
        500, ge=1, description="Largest sites x months product a data query may span."
    )
    max_location_roots: int = Field(
        20, ge=1, description="Most site codes one neon_find_locations call walks."
    )
    graphql_max_query_chars: int = Field(
        8000, ge=100, description="Longest query neon_graphql accepts."
    )
    graphql_max_depth: int = Field(
        8, ge=1, description="Deepest selection set neon_graphql accepts."
    )
    graphql_max_response_bytes: int = Field(
        50_000, ge=1000, description="Default neon_graphql response budget."
    )
    graphql_hard_max_response_bytes: int = Field(
        200_000, ge=1000, description="Largest max_bytes a neon_graphql caller may request."
    )
    max_document_bytes: int = Field(
        25 * 1024 * 1024,
        ge=1024,
        description="Largest document neon_get_document extracts text from (in memory).",
    )
    tools_list_max_bytes: int = Field(
        64_000, ge=1000, description="Conformance bound on the serialized tools/list result."
    )


class DownloadsConfig(_Section):
    """Local downloads (stdio only)."""

    enabled: bool | None = Field(
        None,
        description="Offer neon_download_files. Unset: true on stdio; never available over http.",
    )
    directory: Path = Field(
        Path("~/neon-downloads"),
        validate_default=True,
        description="Directory every download is confined to (created on first use).",
    )
    max_files_per_call: int = Field(
        50, ge=1, description="Most files one neon_download_files call transfers."
    )
    max_bytes_per_call: int = Field(
        2 * 1024**3, ge=1, description="Most bytes one neon_download_files call transfers."
    )
    max_file_bytes: int = Field(
        1024**3, ge=1, description="Largest single file neon_download_files accepts."
    )
    verify_checksums: bool = Field(True, description="Verify MD5 checksums NEON publishes.")
    allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "data.neonscience.org",
            "storage.googleapis.com",
            "*.storage.googleapis.com",
        ],
        description="Hosts downloads (and their redirects) may come from; '*.' is a subdomain wildcard.",
    )

    @field_validator("directory", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class ServerConfig(_Section):
    """Transport, HTTP binding and per-request token handling."""

    transport: Transport = Field(
        "stdio", description="stdio (local clients) or http (stateless Streamable HTTP at /mcp)."
    )
    bind_address: str = Field("127.0.0.1", description="HTTP bind address.")
    bind_port: int = Field(8080, ge=1, le=65535, description="HTTP bind port.")
    public_base_url: str | None = Field(
        None,
        description="Public URL of a hosted deployment; its host/origin join the allow-lists and "
        "https:// enables per-request tokens.",
    )
    allowed_hosts: list[str] = Field(
        default_factory=list, description="Host header allow-list (DNS-rebinding protection)."
    )
    allowed_origins: list[str] = Field(
        default_factory=list, description="Origin header allow-list (DNS-rebinding protection)."
    )
    dns_rebinding_protection: bool | None = Field(
        None,
        description="Force DNS-rebinding protection on/off. "
        "Unset: SDK default (on for loopback binds or when allow-lists are set).",
    )
    json_response: bool = Field(
        False, description="Answer POST /mcp with application/json instead of a single SSE frame."
    )
    max_request_body_size: int = Field(
        1024 * 1024, ge=1024, description="Largest accepted request body in bytes."
    )
    accept_header_token: bool = Field(
        True, description="HTTP: honour a per-request NEON token header (subject to the TLS gate)."
    )
    request_token_header: str = Field(
        "X-API-Token", description="Header carrying a caller's NEON token in HTTP mode."
    )
    allow_insecure_header_token: bool = Field(
        False,
        description="Accept header tokens when public_base_url is not https:// (development only).",
    )
    share_config_token_over_http: bool = Field(
        False,
        description="Lend the operator's configured token to anonymous HTTP callers (private deployments only).",
    )
    tools_list_ttl_ms: int = Field(300_000, ge=0, description="ttlMs advertised on tools/list.")
    log_level: LogLevel = Field("info", description="Log verbosity.")
    instructions_extra: str | None = Field(
        None, description="Text appended to the server instructions."
    )


class Config(BaseModel):
    """Root configuration object."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    neon: NeonConfig = Field(default_factory=NeonConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    downloads: DownloadsConfig = Field(default_factory=DownloadsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    def model_dump_redacted(self) -> dict[str, Any]:
        """JSON-safe dump with the token replaced by ``***`` (for --print-config)."""
        data = self.model_dump(mode="json")
        data["neon"]["api_token"] = "***" if self.neon.api_token is not None else None
        return data

    def token_value(self) -> str | None:
        """The configured token in clear, or ``None`` (never log the result)."""
        if self.neon.api_token is None:
            return None
        value = self.neon.api_token.get_secret_value().strip()
        return value or None

    def effective_downloads_enabled(self, transport: str) -> bool:
        """Downloads exist only on stdio, and only unless explicitly disabled."""
        return transport == "stdio" and self.downloads.enabled is not False

    def effective_prewarm(self, transport: str) -> bool:
        if self.cache.prewarm is not None:
            return self.cache.prewarm
        return transport == "http"

    def effective_token_for_public(self, transport: str) -> bool:
        if self.neon.token_for_public_endpoints is not None:
            return self.neon.token_for_public_endpoints
        return transport == "stdio"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _coerce_env_value(raw: str) -> Any:
    """Env values stay strings (pydantic coerces them); null-ish become ``None``."""
    if raw.strip().lower() in {"", "null", "none"}:
        return None
    return raw


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def _load_env(env: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = [p.lower() for p in key[len(ENV_PREFIX) :].split(ENV_DELIM) if p]
        if not parts:
            continue
        cursor: dict[str, Any] = out
        conflict = False
        for part in parts[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):
                conflict = True
                break
            cursor = nxt
        if not conflict:
            cursor[parts[-1]] = _coerce_env_value(raw)
    return out


def _unwrap_optional(annotation: Any) -> list[Any]:
    origin = get_origin(annotation)
    if origin in (Union, _pytypes.UnionType):
        return [a for a in get_args(annotation) if a is not type(None)]
    return [annotation]


def _is_list(annotation: Any) -> bool:
    return any(get_origin(a) is list for a in _unwrap_optional(annotation))


def _submodel(annotation: Any) -> type[BaseModel] | None:
    for a in _unwrap_optional(annotation):
        if isinstance(a, type) and issubclass(a, BaseModel):
            return a
    return None


def _normalize_lists(data: dict[str, Any], model: type[BaseModel]) -> None:
    """Split comma-separated strings destined for list fields (env convenience)."""
    for name, field in model.model_fields.items():
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, str) and _is_list(field.annotation):
            data[name] = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, dict):
            sub = _submodel(field.annotation)
            if sub is not None:
                _normalize_lists(value, sub)


def _warn_unknown_keys(
    layer: Mapping[str, Any], model: type[BaseModel] = Config, *, source: str, prefix: str = ""
) -> list[str]:
    """Log (and return) dotted keys no model field consumes."""
    unknown: list[str] = []
    for key, value in layer.items():
        dotted = f"{prefix}{key}"
        field = model.model_fields.get(key)
        if field is None:
            unknown.append(dotted)
            logger.warning(
                "config: unknown key %r from %s ignored (check spelling)", dotted, source
            )
            continue
        sub = _submodel(field.annotation)
        if sub is not None and isinstance(value, dict):
            unknown.extend(_warn_unknown_keys(value, sub, source=source, prefix=f"{dotted}."))
    return unknown


_FLAG_PATHS: dict[str, tuple[str, str]] = {
    "transport": ("server", "transport"),
    "bind_address": ("server", "bind_address"),
    "bind_port": ("server", "bind_port"),
    "log_level": ("server", "log_level"),
    "download_dir": ("downloads", "directory"),
    "downloads_enabled": ("downloads", "enabled"),
    "prewarm": ("cache", "prewarm"),
}


def _flags_to_layer(flag_overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    layer: dict[str, Any] = {}
    for key, value in (flag_overrides or {}).items():
        if value is None:
            continue
        if key not in _FLAG_PATHS:
            raise KeyError(f"unknown flag override {key!r}")
        section, field = _FLAG_PATHS[key]
        layer.setdefault(section, {})[field] = value
    return layer


def load_config(
    path: Path | None = None,
    *,
    flag_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration with precedence flag > env > YAML > defaults."""
    source_env = os.environ if env is None else env
    yaml_layer = _load_yaml(path) if path is not None else {}
    env_layer = _load_env(source_env)
    flag_layer = _flags_to_layer(flag_overrides)

    _warn_unknown_keys(yaml_layer, source="config file")
    _warn_unknown_keys(env_layer, source="environment")

    merged = _deep_merge(_deep_merge(yaml_layer, env_layer), flag_layer)
    neon = merged.get("neon")
    if not (isinstance(neon, dict) and neon.get("api_token")):
        for name in TOKEN_ENV_FALLBACKS:
            value = source_env.get(name, "").strip()
            if value:
                merged.setdefault("neon", {})
                if isinstance(merged["neon"], dict):
                    merged["neon"]["api_token"] = value
                break
    _normalize_lists(merged, Config)
    return Config.model_validate(merged)


# ---------------------------------------------------------------------------
# Process-wide active config
# ---------------------------------------------------------------------------

_active_config: Config | None = None


def set_active_config(config: Config | None) -> None:
    """Record (or clear) the resolved config; called by the CLI entry point."""
    global _active_config
    _active_config = config


def get_active_config() -> Config:
    """The config set by the entry point, or env + defaults when none was set."""
    return _active_config if _active_config is not None else load_config()
