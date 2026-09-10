"""Tolerant code resolution for product and site inputs.

Exact codes take a fast path (no catalog). Anything else is matched against
the cached catalog; a match is accepted when it is an exact name, or when its
score is at least 0.75 **and** at least 1.15 times the runner-up, and is echoed in the
result's ``resolved`` list. Otherwise the tool fails with ``ambiguous_input``
(up to eight candidates) or ``not_found`` (with ``didYouMean``). Resolution
never elicits: ranked candidates serve LLM callers better than a form.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from neon_mcp.errors import ToolError
from neon_mcp.models.common import Resolved
from neon_mcp.neon.catalog import Candidate, normalize_product_code

if TYPE_CHECKING:
    from neon_mcp.context import ToolContext

ACCEPT_SCORE = 0.75
ACCEPT_MARGIN = 1.15
NOT_FOUND_BELOW = 0.45
MAX_CANDIDATES = 8
_SITE_CODE_RE = re.compile(r"^[A-Za-z]{4}$")
_STRICT_PRODUCT_RE = re.compile(r"^(NEON\.(DOM\.SITE\.)?)?DP[0-4]\.\d{5}(\.\d{3})?$", re.IGNORECASE)


def _decide(
    candidates: Sequence[Candidate], *, field: str, value: str, kind: str
) -> tuple[str, Resolved]:
    if not candidates or candidates[0].score < NOT_FOUND_BELOW:
        raise ToolError(
            "not_found",
            f"No NEON {kind} matches {value!r}.",
            details={
                "field": field,
                "input": value,
                "didYouMean": [{"code": c.code, "label": c.label} for c in candidates[:3]],
            },
            hint=f"Search with neon_search_{kind}s, or pass an exact {kind} code.",
        )
    top = candidates[0]
    runner = candidates[1].score if len(candidates) > 1 else 0.0
    exact = top.score >= 1.0 and runner < 1.0  # exact code or exact name wins outright
    if exact or (
        top.score >= ACCEPT_SCORE and (runner == 0.0 or top.score >= ACCEPT_MARGIN * runner)
    ):
        return top.code, Resolved(
            field=field, input=value, code=top.code, confidence=round(top.score, 2)
        )
    raise ToolError(
        "ambiguous_input",
        f"{value!r} matches several NEON {kind}s; call again with one of the candidate codes.",
        details={
            "field": field,
            "input": value,
            "candidates": [
                {"code": c.code, "label": c.label, "score": c.score}
                for c in candidates[:MAX_CANDIDATES]
            ],
        },
    )


async def resolve_product(
    value: str, ctx: ToolContext, *, field: str = "product"
) -> tuple[str, Resolved | None]:
    """A product code for ``value`` (a code, short code, or name fragment)."""
    text = value.strip()
    if _STRICT_PRODUCT_RE.match(text):
        code = normalize_product_code(text)
        if code:
            return code, None
    index = await ctx.catalog.products(token=ctx.token, stats=ctx.stats)
    code, resolved = _decide(
        index.fuzzy_candidates(text, MAX_CANDIDATES), field=field, value=text, kind="product"
    )
    return code, resolved


async def resolve_site(
    value: str, ctx: ToolContext, *, field: str = "site"
) -> tuple[str, Resolved | None]:
    """A site code for ``value`` (``HARV``, ``harv`` or ``"Harvard Forest"``)."""
    text = value.strip()
    if _SITE_CODE_RE.match(text):
        upper = text.upper()
        warm = ctx.catalog.peek_sites()
        if warm is None or upper in warm.codes():
            return upper, None
    index = await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)
    if text.upper() in index.codes():
        return text.upper(), None
    code, resolved = _decide(
        index.fuzzy_candidates(text, MAX_CANDIDATES), field=field, value=text, kind="site"
    )
    return code, resolved


async def resolve_sites(
    values: Sequence[str], ctx: ToolContext, *, field: str = "site_codes"
) -> tuple[list[str], list[Resolved]]:
    """Resolve each element, de-duplicating while preserving order."""
    codes: list[str] = []
    resolved: list[Resolved] = []
    for value in values:
        code, res = await resolve_site(value, ctx, field=field)
        if code not in codes:
            codes.append(code)
        if res is not None:
            resolved.append(res)
    return codes, resolved


__all__ = [
    "ACCEPT_MARGIN",
    "ACCEPT_SCORE",
    "MAX_CANDIDATES",
    "normalize_product_code",
    "resolve_product",
    "resolve_site",
    "resolve_sites",
]
