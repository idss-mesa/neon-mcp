"""Logging for neon-mcp (structlog).

``stdio`` MUST keep stdout for MCP framing, so every log line goes to stderr:
a console renderer for stdio, JSON for HTTP deployments.

Never log credentials. The :func:`redact_secrets` processor masks values of
keys that look like credentials (``token``, ``authorization``,
``x-api-token``, ...) and replaces any registered secret (every NEON token the
process sees is registered via :func:`register_secret`) wherever it appears in
a logged string.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_SECRET_KEY_RE = re.compile(r"(?i)token|authorization|secret|password")
_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret so the log processor masks it wherever it appears."""
    if value and len(value) >= 4:
        _SECRETS.add(value)


def registered_secrets() -> frozenset[str]:
    """Snapshot of every registered secret (used by error redaction)."""
    return frozenset(_SECRETS)


def forget_secrets() -> None:
    """Test helper: clear the registered-secret set."""
    _SECRETS.clear()


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        for secret in _SECRETS:
            if secret in value:
                value = value.replace(secret, "***")
        return value
    if isinstance(value, dict):
        return {k: ("***" if _is_secret_key(k, v) else _mask(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask(v) for v in value]
    return value


def _is_secret_key(key: Any, value: Any) -> bool:
    # Booleans/None such as ``token_configured`` are flags, not secrets.
    return isinstance(key, str) and isinstance(value, str) and bool(_SECRET_KEY_RE.search(key))


def redact_secrets(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: mask credential-looking keys and registered secrets."""
    del logger, method_name
    for key in list(event_dict):
        value = event_dict[key]
        event_dict[key] = "***" if _is_secret_key(key, value) else _mask(value)
    return event_dict


class _StdlibSecretFilter(logging.Filter):
    """Mask registered secrets in records from non-structlog libraries."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _SECRETS:
            record.msg = _mask(str(record.msg))
            if record.args:
                record.args = (
                    tuple(_mask(a) for a in record.args)
                    if isinstance(record.args, tuple)
                    else record.args
                )
        return True


class _Stderr:
    """File-like proxy resolving ``sys.stderr`` at write time (survives stream swaps)."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def setup_logging(level: str = "info", transport: str = "stdio") -> None:
    """Configure structlog + stdlib logging for ``transport`` at ``level``."""
    log_level = _LEVEL_MAP.get(level.lower(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(message)s", stream=_Stderr(), force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_StdlibSecretFilter())
    # httpx/httpcore log full request URLs (signed URLs, query strings) at INFO.
    for noisy in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer: Any
    if transport == "stdio":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=_Stderr()),  # type: ignore[arg-type]
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger (bound to ``name`` when given)."""
    return structlog.get_logger(name) if name else structlog.get_logger()
