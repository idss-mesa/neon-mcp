from __future__ import annotations

import pytest

from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter
from tests.helpers import call_err, call_ok


def site_codes(payload: dict) -> list[str]:  # type: ignore[type-arg]
    return [item["siteCode"] for item in payload["items"]]


async def test_search_all_sites_with_facets(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_search_sites", {})
    assert site_codes(payload) == ["ABBY", "HARV", "SRER"]
    assert payload["facets"]["siteTypes"] == {"CORE": 2, "GRADIENT": 1}
    assert (
        payload["items"][0]["productCount"] == 5
        and payload["items"][0]["latestRelease"] == "RELEASE-2026"
    )
    assert router.paths() == ["POST graphql:NeonMcpSitesCatalog"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"query": "Harvard"}, ["HARV"]),
        ({"state_code": "ma"}, ["HARV"]),
        ({"site_type": "core"}, ["HARV", "SRER"]),
        ({"domain_code": "D14"}, ["SRER"]),
        ({"product": "DP1.00001.001"}, ["ABBY"]),
        ({"query": "HARV"}, ["HARV"]),
    ],
)
async def test_search_filters(server: NeonServer, args: dict, expected: list[str]) -> None:  # type: ignore[type-arg]
    assert site_codes(await call_ok(server, "neon_search_sites", args)) == expected


async def test_search_proximity_elevation_and_paging(
    server: NeonServer, router: FixtureRouter
) -> None:
    near = await call_ok(
        server,
        "neon_search_sites",
        {"latitude": 42.5, "longitude": -72.2, "radius_km": 50, "include_elevation": True},
    )
    assert site_codes(near) == ["HARV"]
    assert (
        near["items"][0]["distanceKm"] < 10 and near["items"][0]["locationElevation"] == 348.12784
    )
    assert "GET /locations/sites" in router.paths()
    paged = await call_ok(server, "neon_search_sites", {"limit": 1, "offset": 1})
    assert site_codes(paged) == ["HARV"] and paged["page"]["nextOffset"] == 2
    scored = await call_ok(server, "neon_search_sites", {"query": "Harvard"})
    assert scored["items"][0]["score"] > 0 and "name" in scored["items"][0]["matchedOn"]


async def test_search_validation(server: NeonServer) -> None:
    await call_err(server, "neon_search_sites", {"latitude": 42.5}, "invalid_argument")
    await call_err(server, "neon_search_sites", {"state_code": "Massachusetts"}, "invalid_argument")
    empty = await call_ok(server, "neon_search_sites", {"query": "zzqqxx"})
    assert empty["items"] == [] and empty["nextSteps"]


async def test_get_site_default(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_site", {"site": "HARV"})
    assert router.paths() == ["GET /sites/HARV"]
    assert payload["siteName"].startswith("Harvard Forest") and payload["domainCode"] == "D01"
    assert payload["urls"]["portal"] == "https://www.neonscience.org/field-sites/harv"
    assert payload["deimsId"].startswith("https://deims.org/")
    products = payload["dataProducts"]
    assert len(products) == 5 and products[0]["dataProductCode"] == "DP1.00001.001"
    assert products[0]["ranges"] and products[0]["provisionalMonths"] >= 0
    assert "releases" not in payload and "location" not in payload
    assert payload["nextSteps"][0].startswith("neon_get_availability(site='HARV')")


async def test_get_site_all_sections(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_site", {"site": "Harvard Forest", "include": ["all"]})
    assert payload["resolved"][0]["code"] == "HARV"
    assert [r["release"] for r in payload["releases"]] == ["RELEASE-2025", "RELEASE-2026"]
    assert (
        payload["location"]["locationElevation"] == 348.12784
        and payload["location"]["locationUtmZone"] == 18
    )
    assert len(payload["location"]["locationProperties"]) >= 30
    assert "GET /locations/HARV" in router.paths()


async def test_get_site_filters_paging_and_errors(server: NeonServer) -> None:
    temps = await call_ok(
        server, "neon_get_site", {"site": "HARV", "products_query": "temperature"}
    )
    assert temps["dataProducts"] and all(
        "temperature" in p["dataProductTitle"].lower() for p in temps["dataProducts"]
    )
    paged = await call_ok(server, "neon_get_site", {"site": "HARV", "products_limit": 2})
    assert len(paged["dataProducts"]) == 2 and paged["dataProductsPage"]["nextOffset"] == 2
    missing = await call_err(server, "neon_get_site", {"site": "ZZZZ"}, "not_found")
    assert "ZZZZ" in missing["message"]
