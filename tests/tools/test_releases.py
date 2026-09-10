from __future__ import annotations

from typing import Any

from neon_mcp.server import NeonServer
from tests.fixture_router import RELEASE_2025_UUID, FixtureRouter, Reply, Route, load_fixture
from tests.helpers import call_err, call_ok


def _release_2026_route(router: FixtureRouter) -> None:
    entry: dict[str, Any] = next(
        r for r in load_fixture("releases.json")["data"] if r["release"] == "RELEASE-2026"
    )
    router.add(Route("GET", "/releases/RELEASE-2026", Reply(json={"data": entry}), params={}))


async def test_list_releases(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_list_releases", {})
    assert [r["release"] for r in payload["items"]] == ["RELEASE-2026", "RELEASE-2025"]
    assert payload["latestRelease"] == "RELEASE-2026"
    assert (
        payload["items"][1]["uuid"] == RELEASE_2025_UUID
        and payload["items"][0]["productCount"] == 3
    )
    assert "url" not in payload["items"][0]["artifacts"][0]
    with_urls = await call_ok(server, "neon_list_releases", {"include_artifact_urls": True})
    assert "X-Goog-Signature=REDACTED" in with_urls["items"][0]["artifacts"][0]["url"]
    assert router.paths() == ["GET /releases"]  # second call served from cache


async def test_get_release_products(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_release", {"release": "release-2025"})
    assert router.paths() == ["GET /releases/RELEASE-2025"]
    assert payload["release"] == "RELEASE-2025" and payload["productCount"] == 5
    first = payload["dataProducts"][0]
    assert first == {
        "productCode": "DP1.00001.001",
        "productName": first["productName"],
        "productDescription": first["productDescription"],
        "productDoi": "https://doi.org/10.48443/te3v-2m97",
    }
    assert payload["productsPage"]["total"] == 5
    assert (
        "neon_get_citation(product='DP1.00001.001', release='RELEASE-2025')"
        in payload["nextSteps"][0]
    )
    filtered = await call_ok(
        server, "neon_get_release", {"release": "RELEASE-2025", "product_query": "wind"}
    )
    assert [p["productCode"] for p in filtered["dataProducts"]] == ["DP1.00001.001"]
    paged = await call_ok(
        server, "neon_get_release", {"release": "RELEASE-2025", "products_limit": 2}
    )
    assert paged["productsPage"]["nextOffset"] == 2


async def test_get_release_by_uuid_latest_and_sections(
    server: NeonServer, router: FixtureRouter
) -> None:
    by_uuid = await call_ok(server, "neon_get_release", {"release": RELEASE_2025_UUID.upper()})
    assert by_uuid["release"] == "RELEASE-2025"
    _release_2026_route(router)
    latest = await call_ok(server, "neon_get_release", {"release": "latest", "include": ["all"]})
    assert latest["release"] == "RELEASE-2026"
    assert [s["siteCode"] for s in latest["sites"]] == ["ABBY", "ARIK", "BARC", "BARR", "BART"]
    assert latest["artifacts"][0]["type"] == "MANIFEST_AVAILABLE"
    assert "POST graphql:NeonMcpSitesForRelease" in router.paths()


async def test_release_scoped_product_and_site(server: NeonServer, router: FixtureRouter) -> None:
    router.add(Route("GET", "/releases/RELEASE-2025/sites/ABBY", Reply(fixture="site_ABBY.json")))
    payload = await call_ok(
        server,
        "neon_get_release",
        {
            "release": "RELEASE-2025",
            "include": [],
            "product_code": "DP1.00001.001",
            "site_code": "abby",
        },
    )
    assert payload["product"]["productCode"] == "DP1.00001.001"
    assert [r["release"] for r in payload["product"]["releases"]] == ["RELEASE-2025"]
    assert payload["site"]["siteCode"] == "ABBY" and "dataProducts" not in payload


async def test_release_errors(server: NeonServer, router: FixtureRouter) -> None:
    missing = await call_err(server, "neon_get_release", {"release": "RELEASE-1999"}, "not_found")
    assert missing["details"]["validReleases"] == [f"RELEASE-{y}" for y in range(2021, 2027)]
    await call_err(server, "neon_get_release", {"release": "PROVISIONAL"}, "invalid_argument")
    unknown_uuid = await call_err(
        server, "neon_get_release", {"release": "00000000-0000-4000-8000-000000000000"}, "not_found"
    )
    assert unknown_uuid["details"]["validReleases"] == ["RELEASE-2025", "RELEASE-2026"]
    router.fail_graphql = True
    _release_2026_route(router)
    no_sites = await call_ok(
        server, "neon_get_release", {"release": "RELEASE-2026", "include": ["sites"]}
    )
    assert "sites" not in no_sites and any("Site list unavailable" in n for n in no_sites["notes"])
