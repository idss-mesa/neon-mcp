"""Availability rows: NEON month lists -> compact month ranges per release.

GraphQL ``filterProducts``/``filterSites`` window ``availableMonths`` but not
``availableReleases[].availableMonths`` (verified 2026-09-10), so every
per-release list is clipped locally to the requested window here. The REST
fallback feeds the same function, so both paths produce identical rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import Field

from neon_mcp.models.common import MonthRange, NeonOutput, Page, ToolResultBase, Window
from neon_mcp.neon.months import MonthRanges

PROVISIONAL = "PROVISIONAL"
Provisional = Literal["include", "exclude", "only"]
Format = Literal["ranges", "months", "counts"]
MAX_MONTH_CELLS = 2000


class AvailabilityRow(NeonOutput):
    site_code: str | None = None
    data_product_code: str | None = None
    name: str | None = None
    month_count: int
    month_range: MonthRange | None = None
    ranges: list[str] | None = None
    months: list[str] | None = None
    by_release: dict[str, list[str] | int] = Field(default_factory=dict)


class ReleaseBreakdown(NeonOutput):
    release: str
    row_count: int
    site_months: int
    month_range: MonthRange | None = None


class AvailabilityTotals(NeonOutput):
    row_count: int
    total_site_months: int
    provisional_site_months: int
    month_range: MonthRange | None = None
    releases: list[ReleaseBreakdown] = Field(default_factory=list)


class AvailabilityMatrix(ToolResultBase):
    budget_list: ClassVar[str | None] = "rows"

    mode: Literal["product", "site", "cell"]
    product_code: str | None = None
    product_name: str | None = None
    site_code: str | None = None
    site_name: str | None = None
    release: str | None = None
    provisional: Provisional
    window: Window | None = None
    format: Format
    summary: AvailabilityTotals
    rows: list[AvailabilityRow]
    page: Page


@dataclass
class Cell:
    """Availability of one (site, product) pair after filtering."""

    key: str
    name: str | None
    months: MonthRanges
    by_release: dict[str, MonthRanges] = field(default_factory=dict)


def range_of(months: MonthRanges) -> MonthRange | None:
    first, last = months.first(), months.last()
    return MonthRange(start=first, end=last) if first and last else None


def cell_from_raw(
    key: str,
    name: str | None,
    available_months: Iterable[str] | None,
    available_releases: Sequence[Mapping[str, Any]] | None,
    *,
    start: str | None,
    end: str | None,
    provisional: Provisional,
) -> Cell:
    by_release: dict[str, MonthRanges] = {}
    for entry in available_releases or []:
        tag = entry.get("release")
        if not isinstance(tag, str) or not tag:
            continue
        if provisional == "exclude" and tag == PROVISIONAL:
            continue
        if provisional == "only" and tag != PROVISIONAL:
            continue
        months = MonthRanges.from_months(entry.get("availableMonths") or []).clip(start, end)
        if months:
            by_release[tag] = by_release.get(tag, MonthRanges()).union(months)
    if by_release:
        total = MonthRanges()
        for months in by_release.values():
            total = total.union(months)
    elif not available_releases and provisional == "include":
        total = MonthRanges.from_months(available_months or []).clip(start, end)
    else:
        total = MonthRanges()
    return Cell(key=key, name=name, months=total, by_release=by_release)


def row_from_cell(
    cell: Cell, *, mode: Literal["product", "site", "cell"], fmt: Format
) -> AvailabilityRow:
    def render(months: MonthRanges) -> list[str] | int:
        if fmt == "months":
            return months.months()
        if fmt == "counts":
            return months.count()
        return months.ranges()

    return AvailabilityRow(
        site_code=cell.key if mode != "site" else None,
        data_product_code=cell.key if mode == "site" else None,
        name=cell.name,
        month_count=cell.months.count(),
        month_range=range_of(cell.months),
        ranges=cell.months.ranges() if fmt == "ranges" else None,
        months=cell.months.months() if fmt == "months" else None,
        by_release={tag: render(m) for tag, m in sorted(cell.by_release.items(), reverse=True)},
    )


def totals(cells: Sequence[Cell]) -> AvailabilityTotals:
    overall = MonthRanges()
    per_release: dict[str, tuple[int, int, MonthRanges]] = {}
    for cell in cells:
        overall = overall.union(cell.months)
        for tag, months in cell.by_release.items():
            rows, site_months, span = per_release.get(tag, (0, 0, MonthRanges()))
            per_release[tag] = (rows + 1, site_months + months.count(), span.union(months))
    provisional = per_release.get(PROVISIONAL, (0, 0, MonthRanges()))[1]
    return AvailabilityTotals(
        row_count=len(cells),
        total_site_months=sum(c.months.count() for c in cells),
        provisional_site_months=provisional,
        month_range=range_of(overall),
        releases=[
            ReleaseBreakdown(release=tag, row_count=r, site_months=sm, month_range=range_of(span))
            for tag, (r, sm, span) in sorted(per_release.items(), reverse=True)
        ],
    )


def month_cells(cells: Sequence[Cell]) -> int:
    return sum(c.months.count() for c in cells)
