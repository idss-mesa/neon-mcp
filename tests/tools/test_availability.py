from __future__ import annotations

import pytest

import neon_mcp.tools.availability as availability_tool
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter
from tests.helpers import call_err, call_ok

WIND = "DP1.00001.001"


async def test_product_mode_rows_per_site(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_availability", {"product": WIND})
    assert payload["mode"] == "product" and payload["productName"] == "2D wind speed and direction"
    rows = payload["rows"]
    assert [r["siteCode"] for r in rows] == ["ABBY", "HARV"]
    abby = rows[0]
    assert abby["name"] == "Abby Road NEON" and abby["monthCount"] == 125
    assert abby["ranges"] == ["2016-04/2026-08"]
    assert abby["byRelease"] == {
        "RELEASE-2026": ["2016-04/2025-06"],
        "PROVISIONAL": ["2025-07/2026-08"],
    }
    assert (
        payload["summary"]["totalSiteMonths"] == 268
        and payload["summary"]["provisionalSiteMonths"] == 28
    )
    assert [r["release"] for r in payload["summary"]["releases"]] == ["RELEASE-2026", "PROVISIONAL"]
    assert any("28 provisional site-months" in n for n in payload["notes"])
    assert (
        "neon_list_files(product='DP1.00001.001', site_codes=['ABBY'], start_month='2026-08')"
        in payload["nextSteps"][0]
    )
    assert payload["source"]["via"] == "graphql"
    sent = router.calls_to("POST graphql:NeonMcpProductAvailability")[0].body["variables"]["filter"]
    assert sent == {"productCodes": [WIND]}


async def test_window_clips_release_months(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(
        server,
        "neon_get_availability",
        {"product": WIND, "startDateMonth": "2023-01", "end_month": "2023-06"},
    )
    assert payload["window"] == {"startMonth": "2023-01", "endMonth": "2023-06"}
    abby = payload["rows"][0]
    assert abby["byRelease"] == {"RELEASE-2026": ["2023-01/2023-06"]} and abby["monthCount"] == 6
    assert payload["summary"]["provisionalSiteMonths"] == 0
    assert any("clipped" in n for n in payload["notes"])
    sent = router.calls_to("POST graphql:NeonMcpProductAvailability")[0].body["variables"]["filter"]
    assert sent["startMonth"] == "2023-01" and sent["endMonth"] == "2023-06"


@pytest.mark.parametrize(
    ("provisional", "count", "releases"),
    [
        ("exclude", 111, ["RELEASE-2026"]),
        ("only", 14, ["PROVISIONAL"]),
        ("include", 125, ["RELEASE-2026", "PROVISIONAL"]),
    ],
)
async def test_provisional_modes(
    server: NeonServer, provisional: str, count: int, releases: list[str]
) -> None:
    payload = await call_ok(
        server, "neon_get_availability", {"product": WIND, "provisional": provisional}
    )
    abby = payload["rows"][0]
    assert abby["monthCount"] == count and list(abby["byRelease"]) == releases


async def test_formats(server: NeonServer, monkeypatch: pytest.MonkeyPatch) -> None:
    months = await call_ok(
        server,
        "neon_get_availability",
        {"product": WIND, "start_month": "2023-01", "end_month": "2023-03", "format": "months"},
    )
    assert (
        months["rows"][0]["months"] == ["2023-01", "2023-02", "2023-03"]
        and "ranges" not in months["rows"][0]
    )
    counts = await call_ok(server, "neon_get_availability", {"product": WIND, "format": "counts"})
    assert counts["rows"][0]["byRelease"] == {"RELEASE-2026": 111, "PROVISIONAL": 14}
    assert "ranges" not in counts["rows"][0] and "months" not in counts["rows"][0]
    monkeypatch.setattr(availability_tool, "MAX_MONTH_CELLS", 100)
    err = await call_err(
        server, "neon_get_availability", {"product": WIND, "format": "months"}, "invalid_argument"
    )
    assert "ranges" in err["hint"]


async def test_cell_and_site_modes(server: NeonServer) -> None:
    cell = await call_ok(server, "neon_get_availability", {"product": WIND, "site": "abby"})
    assert (
        cell["mode"] == "cell"
        and cell["format"] == "months"
        and cell["siteName"] == "Abby Road NEON"
    )
    assert [r["siteCode"] for r in cell["rows"]] == ["ABBY"] and len(
        cell["rows"][0]["months"]
    ) == 125
    site = await call_ok(server, "neon_get_availability", {"site": "ABBY"})
    assert site["mode"] == "site" and site["siteName"] == "Abby Road NEON"
    assert site["rows"] == [
        {
            "dataProductCode": WIND,
            "name": "2D wind speed and direction",
            "monthCount": 3,
            "monthRange": {"start": "2024-01", "end": "2024-03"},
            "ranges": ["2024-01/2024-03"],
            "byRelease": {},
        }
    ]
    assert "neon_get_availability(product='DP1.00001.001', site='ABBY')" in site["nextSteps"][0]
    excluded = await call_ok(
        server, "neon_get_availability", {"site": "ABBY", "provisional": "exclude"}
    )
    assert excluded["rows"] == [] and any("omitted" in n for n in excluded["notes"])


async def test_site_filters_and_resolution(server: NeonServer) -> None:
    domain = await call_ok(server, "neon_get_availability", {"product": WIND, "domain_code": "D01"})
    assert [r["siteCode"] for r in domain["rows"]] == ["HARV"]
    named = await call_ok(
        server, "neon_get_availability", {"product": WIND, "site_codes": ["Harvard Forest"]}
    )
    assert [r["siteCode"] for r in named["rows"]] == ["HARV"]
    assert named["resolved"][0] == {
        "field": "site_codes",
        "input": "Harvard Forest",
        "code": "HARV",
        "confidence": named["resolved"][0]["confidence"],
    }
    await call_err(
        server,
        "neon_get_availability",
        {"product": WIND, "domain_code": "D14", "site_codes": ["HARV"]},
        "not_found",
    )


async def test_paging(server: NeonServer) -> None:
    payload = await call_ok(server, "neon_get_availability", {"product": WIND, "limit": 1})
    assert [r["siteCode"] for r in payload["rows"]] == ["ABBY"]
    assert payload["page"]["nextOffset"] == 1 and payload["summary"]["rowCount"] == 2
    assert any("offset=1" in s for s in payload["nextSteps"])


async def test_rest_fallback(server: NeonServer, router: FixtureRouter) -> None:
    router.fail_graphql = True
    payload = await call_ok(server, "neon_get_availability", {"product": WIND})
    assert payload["source"]["via"] == "rest" and any(
        "GraphQL unavailable" in n for n in payload["notes"]
    )
    assert [r["siteCode"] for r in payload["rows"]] == ["ABBY", "ARIK", "BARC"]
    assert payload["rows"][0]["byRelease"] == {
        "RELEASE-2026": ["2025-01/2025-06"],
        "PROVISIONAL": ["2026-03/2026-08"],
    }
    assert "GET /products/DP1.00001.001" in router.paths()


async def test_validation_and_missing(server: NeonServer) -> None:
    for args in (
        {},
        {"product": WIND, "provisional": "only", "release": "RELEASE-2026"},
        {"product": WIND, "site": "ABBY", "site_codes": ["HARV"]},
        {"site": "ABBY", "product_codes": ["DP1.00001.001"], "product": WIND},
        {"product": WIND, "start_month": "2024-01", "end_month": "2023-01"},
        {"product": WIND, "release": "PROVISIONAL"},
        {"product": WIND, "start_month": "2011-12"},
    ):
        await call_err(server, "neon_get_availability", args, "invalid_argument")
    missing = await call_err(
        server, "neon_get_availability", {"product": "DP1.20001.001"}, "not_found"
    )
    assert "DP1.20001.001" in missing["message"]
