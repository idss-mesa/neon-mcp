"""Helpers shared by tool handlers."""

from __future__ import annotations

from collections.abc import Sequence

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError, map_api_error
from neon_mcp.logging import registered_secrets
from neon_mcp.models.common import Source


def api_error(
    exc: NeonApiError, *, entity: str, identifier: str, hint: str | None = None
) -> ToolError:
    """Map an upstream failure with the entity it concerned (for ``not_found`` messages)."""
    err = map_api_error(exc, entity=entity, identifier=identifier, secrets=registered_secrets())
    if hint and err.hint is None:
        err.hint = hint
    return err


def source(ctx: ToolContext, via: str | None = None, *, derived: Sequence[str] = ()) -> Source:
    endpoints = list(ctx.stats.endpoints)
    if via is None:
        if not endpoints:
            via = "local"
        elif all(e == "POST /graphql" for e in endpoints):
            via = "graphql"
        elif "POST /graphql" in endpoints:
            via = "mixed"
        else:
            via = "rest"
    return Source(
        endpoints=endpoints,
        via=via,  # type: ignore[arg-type]
        cached=ctx.stats.requests == 0 and ctx.stats.cache_hits > 0,
        derived=list(derived),
    )


def check_window(start: str | None, end: str | None) -> None:
    if start and end and start > end:
        raise ToolError("invalid_argument", f"start_month {start} is after end_month {end}.")


def fmt_list(values: Sequence[str]) -> str:
    return "[" + ", ".join(repr(v) for v in values) + "]"
