from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neon_mcp.neon.months import MonthRanges, index_month, month_index, months_between

MONTHS = st.integers(min_value=2012 * 12, max_value=2030 * 12).map(index_month)


def test_merging_and_rendering() -> None:
    r = MonthRanges.from_months(["2016-06", "2016-04", "2016-05", "2018-03", "2016-05"])
    assert r.ranges() == ["2016-04/2016-06", "2018-03/2018-03"]
    assert r.count() == len(r) == 4
    assert (r.first(), r.last()) == ("2016-04", "2018-03")
    assert "2016-05" in r and "2017-01" not in r and 5 not in r and "bogus" not in r
    assert list(r) == ["2016-04", "2016-05", "2016-06", "2018-03"]


def test_clip_overlap_union_difference() -> None:
    r = MonthRanges.from_ranges(["2016-04/2017-12", "2019-01/2019-03"])
    assert r.clip("2017-11", "2019-01").ranges() == ["2017-11/2017-12", "2019-01/2019-01"]
    assert r.clip(None, "2016-05").ranges() == ["2016-04/2016-05"]
    assert r.overlaps("2018-01", "2018-12") is False
    assert r.overlaps("2019-03", None) is True
    assert r.union(MonthRanges.from_months(["2018-01"])).count() == r.count() + 1
    assert r.difference(MonthRanges.from_months(["2016-04"])).first() == "2016-05"
    assert not MonthRanges() and MonthRanges().first() is None


def test_parsing_and_helpers() -> None:
    assert month_index("2016-04") == 2016 * 12 + 3
    assert index_month(month_index("2019-12")) == "2019-12"
    assert months_between("2023-01", "2023-12") == 12
    assert months_between("2023-12", "2023-01") == 0
    assert MonthRanges.from_ranges(["2017-12/2016-04"]).ranges() == ["2016-04/2017-12"]
    assert MonthRanges.from_ranges(["2017-12"]).ranges() == ["2017-12/2017-12"]
    with pytest.raises(ValueError):
        month_index("2016-13")
    assert MonthRanges.from_months(None) == MonthRanges()
    assert hash(MonthRanges.from_months(["2020-01"])) == hash(
        MonthRanges.from_ranges(["2020-01/2020-01"])
    )
    assert "2020-01" in repr(MonthRanges.from_months(["2020-01"]))


@given(st.lists(MONTHS, max_size=60))
def test_round_trips(months: list[str]) -> None:
    r = MonthRanges.from_months(months)
    assert r.months() == sorted(set(months))
    assert MonthRanges.from_ranges(r.ranges()) == r


@given(st.lists(MONTHS, max_size=40), MONTHS, MONTHS)
def test_clip_is_subset(months: list[str], a: str, b: str) -> None:
    r = MonthRanges.from_months(months)
    lo, hi = min(a, b), max(a, b)
    clipped = r.clip(lo, hi)
    assert set(clipped.months()) <= set(r.months())
    assert all(lo <= m <= hi for m in clipped.months())
