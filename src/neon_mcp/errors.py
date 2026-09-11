"""Structured error types for neon-mcp.

Tool handlers raise :class:`ToolError` for every user-facing failure; the
server boundary turns it into an ``isError`` tool result whose
``structuredContent`` is ``{"error": {"code", "message", "details", "hint"}}``.
Python tracebacks never reach the wire.

:class:`NeonApiError` is what the HTTP client raises for a failed upstream
call; :func:`map_api_error` translates it into a :class:`ToolError` using the
table in DESIGN.md section 3.5 (notably: NEON answers unknown codes with HTTP
400 "... not found", which maps to ``not_found``, and 403 on a token-only
endpoint maps to ``auth_required``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal

ErrorCode = Literal[
    "invalid_argument",
    "not_found",
    "ambiguous_input",
    "auth_required",
    "forbidden",
    "rate_limited",
    "upstream_error",
    "upstream_unavailable",
    "graphql_error",
    "feature_unavailable",
    "not_available_in_http_mode",
    "download_limit_exceeded",
    "download_denied",
    "checksum_mismatch",
    "query_too_large",
    "result_too_large",
    "catalog_unavailable",
    "unknown_tool",
    "internal_error",
]

#: Resource every ``auth_required`` error points at.
API_TOKEN_GUIDE = "neon://guide/api-token"
#: Where NEON users create an API token.
MYACCOUNT_URL = "https://data.neonscience.org/myaccount"

AUTH_REQUIRED_MESSAGE = (
    "This NEON endpoint requires an API token. Create one at "
    f"{MYACCOUNT_URL} (GET API TOKEN) and set NEON_TOKEN in the server's environment; "
    "in HTTP mode send the X-API-Token header. Discovery tools work without a token."
)

_NOT_FOUND_RE = re.compile(r"not\s+found", re.IGNORECASE)


class ToolError(Exception):
    """A structured, user-facing failure raised from a tool handler.

    ``code`` is a stable machine-readable :data:`ErrorCode`; ``message`` is
    safe to show a user and never contains a token; ``details`` is
    JSON-serializable context; ``hint`` is an optional one-line remedy.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}
        self.hint = hint

    def to_payload(self) -> dict[str, Any]:
        """Return the ``{"error": {...}}`` structure sent as ``structuredContent``."""
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }
        if self.hint:
            error["hint"] = self.hint
        return {"error": error}

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ToolError(code={self.code!r}, message={self.message!r})"


class InputRequired(Exception):
    """Raised by a handler that needs one more round trip with the user (MRTR).

    The server boundary turns it into an ``InputRequiredResult`` carrying an
    ``elicitation/create`` form. ``state`` travels out to the client and back
    as ``requestState``; it must hold only the question being asked — never a
    token, a filesystem path or an authorization decision — because the client
    controls it by the time it returns.
    """

    def __init__(
        self,
        *,
        key: str,
        message: str,
        requested_schema: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        self.key = key
        self.message = message
        self.requested_schema: dict[str, Any] = dict(requested_schema)
        self.state: dict[str, Any] = dict(state)


class NeonApiError(Exception):
    """A failed NEON API call, raised by :class:`neon_mcp.neon.client.NeonClient`.

    ``kind`` distinguishes an HTTP error status (``http``), a network failure
    or timeout after retries (``transport``, ``status == 0``) and a response
    that was not the JSON we expected (``decode``).
    """

    def __init__(
        self,
        status: int,
        detail: str,
        path: str,
        *,
        retry_after_s: float | None = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        kind: Literal["http", "transport", "decode"] = "http",
        content_type: str | None = None,
        token_sent: bool = False,
    ) -> None:
        super().__init__(f"{status} {path}: {detail}")
        self.status = status
        self.detail = detail
        self.path = path
        self.retry_after_s = retry_after_s
        self.data = data
        self.headers: dict[str, str] = dict(headers or {})
        self.kind = kind
        self.content_type = content_type
        #: Whether the failed request carried an X-API-Token header.
        self.token_sent = token_sent


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each non-empty secret in ``text`` with ``***``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def map_api_error(
    exc: NeonApiError,
    *,
    token_sent: bool | None = None,
    requires_token: bool = False,
    entity: str | None = None,
    identifier: str | None = None,
    secrets: Iterable[str] = (),
) -> ToolError:
    """Translate an upstream failure into a :class:`ToolError` (DESIGN.md 3.5)."""
    secrets = tuple(secrets)
    if token_sent is None:
        token_sent = exc.token_sent
    detail = redact(exc.detail or "", secrets)[:500]
    endpoint = redact(exc.path, secrets)

    if exc.kind == "transport":
        return ToolError(
            "upstream_unavailable",
            "The NEON API could not be reached (network error or timeout).",
            details={"reason": detail, "endpoint": endpoint},
            hint="Retry in a moment; call neon_ping(check_api=true) to test connectivity.",
        )
    if exc.kind == "decode":
        return ToolError(
            "upstream_error",
            "The NEON API returned a response that was not valid JSON.",
            details={"status": exc.status, "contentType": exc.content_type, "endpoint": endpoint},
        )

    status = exc.status
    if status == 403:
        if not token_sent:
            return ToolError(
                "auth_required",
                AUTH_REQUIRED_MESSAGE,
                details={"guide": API_TOKEN_GUIDE, "endpoint": endpoint, "tokenSource": "none"},
                hint="Read neon://guide/api-token.",
            )
        return ToolError(
            "forbidden",
            "NEON rejected the API token (HTTP 403); it is usually mistyped, disabled or "
            "deleted, and NEON refuses every request that carries it. Check the NEON_TOKEN "
            f"value (or the X-API-Token header) or create a new token at {MYACCOUNT_URL}.",
            details={"guide": API_TOKEN_GUIDE, "endpoint": endpoint},
            hint="Read neon://guide/api-token.",
        )
    if status == 404 or (status == 400 and _NOT_FOUND_RE.search(exc.detail or "")):
        details: dict[str, Any] = {"endpoint": endpoint}
        if entity:
            details["entity"] = entity
        if identifier:
            details["identifier"] = identifier
        if isinstance(exc.data, Mapping) and exc.data.get("validReleases"):
            details["validReleases"] = list(exc.data["validReleases"])
        what = f"{entity} {identifier!r}" if entity and identifier else "The requested item"
        return ToolError("not_found", f"{what} was not found. NEON said: {detail}", details=details)
    if status == 400:
        return ToolError(
            "invalid_argument",
            f"NEON rejected the request: {detail}",
            details={"endpoint": endpoint},
        )
    if status == 429:
        return ToolError(
            "rate_limited",
            "The NEON API rate limit was exceeded; wait before retrying.",
            details={
                "retryAfterSeconds": exc.retry_after_s,
                "limit": _int_header(exc.headers, "x-ratelimit-limit"),
                "remaining": _int_header(exc.headers, "x-ratelimit-remaining"),
                "identity": "token" if token_sent else "anonymous",
            },
            hint=None if requires_token or token_sent else "A NEON API token raises the limit.",
        )
    if status >= 500:
        return ToolError(
            "upstream_error",
            f"The NEON API failed with HTTP {status}.",
            details={"status": status, "endpoint": endpoint, "body": detail[:200]},
        )
    return ToolError(
        "upstream_error",
        f"The NEON API answered HTTP {status}: {detail}",
        details={"status": status, "endpoint": endpoint},
    )


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    for key, value in headers.items():
        if key.lower() == name:
            try:
                return int(value)
            except ValueError:
                return None
    return None
