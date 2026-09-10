from __future__ import annotations

import pytest

from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter
from tests.helpers import call_err, call_ok


def codes(payload: dict) -> list[str]:  # type: ignore[type-arg]
    return [item["productCode"] for item in payload["items"]]


async def test_search_defaults_to_active_and_ranks(
    server: NeonServer, router: FixtureRouter
) -> None:
    payload = await call_ok(server, "neon_search_products", {"query": "wind"})
    assert codes(payload) == ["DP1.00001.001"]
    item = payload["items"][0]
    assert item["score"] > 0 and "name" in item["matchedOn"]
    assert item["siteCount"] == 3 and item["monthRange"] == {"start": "2026-03", "end": "2026-08"}
    assert (
        item["productCategory"] == "Level 1 Data Product"
        and item["latestRelease"] == "RELEASE-2026"
    )
    assert payload["indexSource"] == "graphql" and "productCategory" in payload["source"]["derived"]
    assert "neon_get_availability(product='DP1.00001.001')" in payload["nextSteps"][0]
    assert router.paths() == ["POST graphql:NeonMcpProductsCatalog"]
    everything = await call_ok(server, "neon_search_products", {"query": "wind", "status": "all"})
    assert codes(everything) == ["DP1.00001.001", "DP1.00007.001"]
    assert len(router.calls) == 1  # the catalog is cached


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"theme": "organisms"}, ["DP1.10003.001", "DP1.20002.001"]),
        ({"science_team": "tos"}, ["DP1.10003.001"]),
        ({"site": "ABBY"}, ["DP1.00001.001", "DP1.10003.001", "DP1.30001.001"]),
        ({"domain_code": "d16"}, ["DP1.00001.001", "DP1.10003.001", "DP1.30001.001"]),
        ({"domain_code": "D01"}, []),
        ({"available_from": "2026-09"}, ["DP1.20002.001"]),
        ({"level": 1, "has_expanded": False}, ["DP1.20002.001", "DP1.30001.001"]),
        ({"query": "DP1.10003"}, ["DP1.10003.001"]),
    ],
)
async def test_search_filters(server: NeonServer, args: dict, expected: list[str]) -> None:  # type: ignore[type-arg]
    assert codes(await call_ok(server, "neon_search_products", args)) == expected


async def test_search_paging_facets_and_sorting(server: NeonServer) -> None:
    payload = await call_ok(server, "neon_search_products", {"limit": 2})
    assert payload["page"] == {
        "total": 5,
        "returned": 2,
        "offset": 0,
        "limit": 2,
        "truncated": True,
        "nextOffset": 2,
        "truncatedReason": "limit",
    }
    assert payload["facets"]["productStatus"] == {"ACTIVE": 5}
    assert set(payload["facets"]["scienceTeams"]) == {"AIS", "AOP", "AOS", "TIS", "TOS"}
    assert any("offset=2" in step for step in payload["nextSteps"])
    second = await call_ok(server, "neon_search_products", {"limit": 2, "offset": 2})
    assert not set(codes(second)) & set(codes(payload))
    names = await call_ok(server, "neon_search_products", {"sort": "productName"})
    titles = [i["productName"].lower() for i in names["items"]]
    assert titles == sorted(titles)


async def test_search_no_hits_and_release(server: NeonServer, router: FixtureRouter) -> None:
    empty = await call_ok(server, "neon_search_products", {"query": "zzqx"})
    assert empty["items"] == [] and any("Relax" in s for s in empty["nextSteps"])
    scoped = await call_ok(server, "neon_search_products", {"release": "RELEASE-2025"})
    assert any("RELEASE-2025" in n for n in scoped["notes"])
    assert router.calls[-1].body["variables"] == {"release": "RELEASE-2025"}


async def test_search_validation(server: NeonServer) -> None:
    await call_err(server, "neon_search_products", {"release": "PROVISIONAL"}, "invalid_argument")
    await call_err(
        server,
        "neon_search_products",
        {"available_from": "2020-05", "available_to": "2019-01"},
        "invalid_argument",
    )
    await call_err(server, "neon_search_products", {"limit": 101}, "invalid_argument")
    err = await call_err(server, "neon_search_products", {"sciencTeam": "TOS"}, "invalid_argument")
    assert "science_team" in err["message"]


async def test_search_budget_trims(server: NeonServer) -> None:
    server.config.limits.max_result_bytes = 1000
    payload = await call_ok(server, "neon_search_products", {"status": "ALL", "limit": 100})
    assert payload["page"]["truncatedReason"] == "budget" and len(payload["items"]) < 6


async def test_get_product_from_catalog(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_product", {"product": "DP1.00001.001"})
    assert router.paths() == ["POST graphql:NeonMcpProductsCatalog"]
    assert payload["productCodeLong"] == "NEON.DOM.SITE.DP1.00001.001"
    assert payload["availability"] == {
        "siteCount": 3,
        "totalSiteMonths": 18,
        "monthRange": {"start": "2026-03", "end": "2026-08"},
    }
    assert [r["release"] for r in payload["releases"]] == ["RELEASE-2025", "RELEASE-2026"]
    assert payload["releases"][1]["productDoi"]["url"] == "https://doi.org/10.48443/d4h5-ys70"
    assert payload["specsCount"] == 2 and "changeLogCount" not in payload
    assert payload["urls"]["portal"] == "https://data.neonscience.org/data-products/DP1.00001.001"
    assert payload["source"]["derived"] and payload["notes"]
    await call_ok(server, "neon_get_product", {"product": "DP1.00001.001"})
    assert len(router.calls) == 1


async def test_get_product_sections_from_rest(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(
        server,
        "neon_get_product",
        {
            "product": "DP1.00001.001",
            "include": [
                "abstract",
                "specs",
                "change_logs",
                "availability",
                "packages",
                "biorepository",
            ],
        },
    )
    assert router.paths() == ["GET /products/DP1.00001.001"]
    assert len(payload["productAbstract"]) == 401 and payload["textTruncated"] == []
    assert [s["specNumber"] for s in payload["specs"]] == ["NEON.DOC.000780vD", "NEON.DOC.011081vD"]
    assert payload["specs"][0]["specUrl"].endswith("/documents/NEON.DOC.000780vD")
    assert {c["id"] for c in payload["changeLogs"]} == {506, 601} and payload["changeLogsPage"][
        "total"
    ] == 2
    assert payload["changeLogCount"] == 2 and payload["biorepositoryCollections"] == []
    rows = payload["availabilityRows"]
    assert [r["siteCode"] for r in rows] == ["ABBY", "ARIK", "BARC"]
    assert rows[0]["byRelease"] == {
        "RELEASE-2026": ["2025-01/2025-06"],
        "PROVISIONAL": ["2026-03/2026-08"],
    }
    assert payload["availability"]["provisionalSiteMonths"] == 18
    assert any(
        "neon_get_document(spec_number='NEON.DOC.000780vD')" in s for s in payload["nextSteps"]
    )


async def test_get_product_paging_budget_and_release(
    server: NeonServer, router: FixtureRouter
) -> None:
    clipped = await call_ok(
        server,
        "neon_get_product",
        {
            "product": "DP1.00001.001",
            "include": ["abstract", "change_logs"],
            "text_budget": 100,
            "change_logs_limit": 1,
        },
    )
    assert (
        clipped["textTruncated"] == ["productAbstract"] and len(clipped["productAbstract"]) <= 100
    )
    assert clipped["changeLogsPage"]["nextOffset"] == 1
    assert any("change_logs_offset=1" in s for s in clipped["nextSteps"])
    scoped = await call_ok(
        server, "neon_get_product", {"product": "DP1.00001.001", "release": "RELEASE-2025"}
    )
    assert [r["release"] for r in scoped["releases"]] == ["RELEASE-2025"]
    assert router.calls[-1].params == {"release": "RELEASE-2025"}
    everything = await call_ok(
        server, "neon_get_product", {"product": "DP1.00001.001", "include": ["all"]}
    )
    assert everything["availabilityRows"] and everything["specs"]


async def test_get_product_resolution_and_errors(server: NeonServer) -> None:
    fuzzy = await call_ok(server, "neon_get_product", {"product": "breeding landbird"})
    assert fuzzy["productCode"] == "DP1.10003.001"
    assert (
        fuzzy["resolved"][0]["field"] == "product"
        and fuzzy["resolved"][0]["code"] == "DP1.10003.001"
    )
    missing = await call_err(
        server,
        "neon_get_product",
        {"product": "DP9.99999.999", "include": ["abstract"]},
        "not_found",
    )
    assert "DP9.99999.999" in missing["message"]
    await call_err(server, "neon_get_product", {"product": "DP9.99999.999"}, "not_found")
    release = await call_err(
        server,
        "neon_get_product",
        {"product": "DP1.00001.001", "release": "RELEASE-1999"},
        "not_found",
    )
    assert release["details"]["validReleases"][-1] == "RELEASE-2026"
    await call_err(
        server,
        "neon_get_product",
        {"product": "DP1.00001.001", "include": ["nope"]},
        "invalid_argument",
    )
