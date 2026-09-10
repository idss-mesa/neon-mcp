"""Helpers shared by every projection module."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from neon_mcp.models.common import Page

T = TypeVar("T")

_TEAM_ABBR_RE = re.compile(r"\(([A-Za-z]{2,6})\)\s*$")


def clip_text(text: str | None, budget: int) -> tuple[str | None, bool]:
    """Clip ``text`` to ``budget`` characters (ending in an ellipsis)."""
    if text is None:
        return None, False
    text = text.strip()
    if len(text) <= budget:
        return text, False
    return text[: max(budget - 1, 0)].rstrip() + "…", True


def paginate(
    items: Sequence[T], *, offset: int, limit: int, total: int | None = None
) -> tuple[list[T], Page]:
    """Slice ``items`` and describe the slice as a :class:`Page`."""
    total = len(items) if total is None else total
    offset = max(offset, 0)
    page_items = list(items[offset : offset + limit])
    returned = len(page_items)
    truncated = offset + returned < total
    return page_items, Page(
        total=total,
        returned=returned,
        offset=offset,
        limit=limit,
        truncated=truncated,
        next_offset=offset + returned if truncated else None,
        truncated_reason="limit" if truncated else None,
    )


def null_list(value: Iterable[T] | None) -> list[T]:
    """NEON returns ``null`` for empty lists; normalise to ``[]``."""
    return list(value) if value is not None else []


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def parse_gcs_expiry(url: str | None) -> str | None:
    """Expiry of a Google Cloud Storage signed URL (X-Goog-Date + X-Goog-Expires), ISO-8601 UTC."""
    if not url:
        return None
    params = {k.lower(): v for k, v in parse_qsl(urlsplit(url).query)}
    date, expires = params.get("x-goog-date"), params.get("x-goog-expires")
    if not date or not expires:
        return None
    try:
        start = datetime.strptime(date, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return (start + timedelta(seconds=int(expires))).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def strip_signature(url: str) -> str:
    """Drop ``X-Goog-*`` query parameters (for logs and ``source``)."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("x-goog-")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def team_abbr(product_science_team: str | None) -> str | None:
    """``"Terrestrial Instrument System (TIS)"`` -> ``"TIS"``."""
    if not product_science_team:
        return None
    match = _TEAM_ABBR_RE.search(product_science_team)
    return match.group(1).upper() if match else None


def product_level(product_code: str) -> int:
    """``DP1.10003.001`` -> 1."""
    try:
        return int(product_code[2])
    except (IndexError, ValueError):
        return 0


def properties_map(
    items: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """Fold ``[{locationPropertyName, locationPropertyValue}]`` into a dict.

    Returns the raw list as the second element only when a name repeats (the
    dict would otherwise silently drop values).
    """
    folded: dict[str, Any] = {}
    duplicate = False
    for item in items or []:
        name = item.get("locationPropertyName")
        if not isinstance(name, str):
            continue
        if name in folded:
            duplicate = True
        folded[name] = item.get("locationPropertyValue")
    return folded, ([dict(i) for i in items] if duplicate and items else None)


def month_range(first: str | None, last: str | None) -> dict[str, str] | None:
    """``{start, end}`` or ``None`` when there are no months."""
    if not first or not last:
        return None
    return {"start": first, "end": last}
