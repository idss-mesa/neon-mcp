"""Compact month-set arithmetic.

NEON reports availability as lists of ``YYYY-MM`` strings (up to ~125 per
site). :class:`MonthRanges` stores them as sorted inclusive integer ranges
(``index = year * 12 + month - 1``) and renders ISO-8601 interval strings
``"2016-04/2017-12"`` (a single month is ``"2016-04/2016-04"``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def month_index(month: str) -> int:
    match = _MONTH_RE.match(month.strip())
    if not match:
        raise ValueError(f"not a YYYY-MM month: {month!r}")
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def index_month(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


class MonthRanges:
    """An immutable set of months stored as merged inclusive ranges."""

    __slots__ = ("_ranges",)

    def __init__(self, ranges: Iterable[tuple[int, int]] = ()) -> None:
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        self._ranges: tuple[tuple[int, int], ...] = tuple(merged)

    @classmethod
    def from_months(cls, months: Iterable[str] | None) -> MonthRanges:
        idx = sorted({month_index(m) for m in (months or []) if m})
        return cls((i, i) for i in idx)

    @classmethod
    def from_ranges(cls, ranges: Iterable[str]) -> MonthRanges:
        pairs: list[tuple[int, int]] = []
        for text in ranges:
            first, _, last = text.partition("/")
            start, end = month_index(first), month_index(last or first)
            pairs.append((min(start, end), max(start, end)))
        return cls(pairs)

    def ranges(self) -> list[str]:
        return [f"{index_month(a)}/{index_month(b)}" for a, b in self._ranges]

    def pairs(self) -> tuple[tuple[int, int], ...]:
        return self._ranges

    def months(self) -> list[str]:
        return [index_month(i) for a, b in self._ranges for i in range(a, b + 1)]

    def count(self) -> int:
        return sum(b - a + 1 for a, b in self._ranges)

    def first(self) -> str | None:
        return index_month(self._ranges[0][0]) if self._ranges else None

    def last(self) -> str | None:
        return index_month(self._ranges[-1][1]) if self._ranges else None

    def clip(self, start: str | None, end: str | None) -> MonthRanges:
        lo = month_index(start) if start else None
        hi = month_index(end) if end else None
        out: list[tuple[int, int]] = []
        for a, b in self._ranges:
            a2 = max(a, lo) if lo is not None else a
            b2 = min(b, hi) if hi is not None else b
            if a2 <= b2:
                out.append((a2, b2))
        return MonthRanges(out)

    def overlaps(self, start: str | None, end: str | None) -> bool:
        return bool(self.clip(start, end))

    def union(self, other: MonthRanges) -> MonthRanges:
        return MonthRanges(self._ranges + other._ranges)

    def difference(self, other: MonthRanges) -> MonthRanges:
        remove = set(other.months())
        return MonthRanges.from_months(m for m in self.months() if m not in remove)

    def __contains__(self, month: object) -> bool:
        if not isinstance(month, str):
            return False
        try:
            i = month_index(month)
        except ValueError:
            return False
        return any(a <= i <= b for a, b in self._ranges)

    def __iter__(self) -> Iterator[str]:
        return iter(self.months())

    def __len__(self) -> int:
        return self.count()

    def __bool__(self) -> bool:
        return bool(self._ranges)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MonthRanges) and self._ranges == other._ranges

    def __hash__(self) -> int:
        return hash(self._ranges)

    def __repr__(self) -> str:
        return f"MonthRanges({self.ranges()!r})"


def months_between(start: str, end: str) -> int:
    """Inclusive count of months from ``start`` to ``end`` (0 when reversed)."""
    return max(month_index(end) - month_index(start) + 1, 0)
