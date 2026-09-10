"""Taxonomy projections (Darwin Core keys kept verbatim)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field

from neon_mcp.models.common import NeonOutput, Page, ToolResultBase


class TaxonPage(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    items: list[dict[str, Any]]
    page: Page
    filters: dict[str, Any] = Field(default_factory=dict)
    fuzzy_fallback_used: bool = False


class _Unused(NeonOutput):  # keeps the module's public surface model-only
    pass


def project_taxon(raw: Mapping[str, Any], *, verbose: bool) -> dict[str, Any]:
    """NEON keys verbatim; verbose rows drop null-valued ranks (24 of 48 keys are often null)."""
    if verbose:
        return {k: v for k, v in raw.items() if v is not None}
    return dict(raw)


def offset_from_next(next_url: str | None) -> int | None:
    if not next_url:
        return None
    for key, value in parse_qsl(urlsplit(next_url).query):
        if key == "offset":
            try:
                return int(value)
            except ValueError:
                return None
    return None
