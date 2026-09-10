from __future__ import annotations

from typing import Any

import pytest

from neon_mcp.errors import NeonApiError
from neon_mcp.neon.catalog import (
    ProductIndex,
    ProductQuery,
    SiteIndex,
    SiteQuery,
    normalize_product_code,
)
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter, Reply, Route, load_fixture


@pytest.fixture
def rest_products() -> ProductIndex:
    return ProductIndex.from_rest(load_fixture("products.json"), release=None)


@pytest.fixture
def rest_sites() -> SiteIndex:
    return SiteIndex.from_rest(load_fixture("sites.json"), release=None)


def test_graphql_and_rest_builds_are_identical(rest_products: ProductIndex) -> None:
    gql = ProductIndex.from_graphql(load_fixture("graphql_products_catalog.json"), release=None)
    assert gql.records == rest_products.records
    sites_gql = SiteIndex.from_graphql(load_fixture("graphql_sites_catalog.json"), release=None)
    assert (
        sites_gql.records == SiteIndex.from_rest(load_fixture("sites.json"), release=None).records
    )


def test_derived_fields_match_rest_values(rest_products: ProductIndex) -> None:
    gql = ProductIndex.from_graphql(load_fixture("graphql_products_catalog.json"), release=None)
    raw = {p["productCode"]: p for p in load_fixture("products.json")["data"]}
    for rec in gql.records:
        src = raw[rec.product_code]
        assert rec.product_science_team_abbr == src["productScienceTeamAbbr"]
        assert rec.product_category == src["productCategory"]
        assert rec.product_code_long == src["productCodeLong"]
        assert rec.product_code_presentation == src["productCodePresentation"]


def test_null_lists_and_record_helpers(rest_products: ProductIndex) -> None:
    future = rest_products.by_code("DP1.00007.001")
    assert future is not None and future.months_by_site == {} and future.site_codes() == ()
    wind = rest_products.by_code("DP1.00001.001")
    assert wind is not None and wind.site_codes() == ("ABBY", "ARIK", "BARC")
    assert wind.all_months().count() == 6 and wind.latest_release() == "RELEASE-2026"
    assert wind.site_month_count() == 18
    assert rest_products.by_code("DP1.20001.001").specs == ()  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("DP1.10003", "DP1.10003.001"),
        ("neon.dp1.10003.001", "DP1.10003.001"),
        ("NEON.DOM.SITE.DP1.00001.001", "DP1.00001.001"),
        ("DP5.00001.001", None),
        ("", None),
    ],
)
def test_normalize_product_code(text: str, code: str | None) -> None:
    assert normalize_product_code(text) == code


def test_product_search_filters_and_ranking(rest_products: ProductIndex) -> None:
    active = rest_products.search(ProductQuery())
    assert "DP1.00007.001" not in [r.product_code for r, *_ in active.items]
    assert rest_products.search(ProductQuery(status="ALL")).total == 6
    wind = rest_products.search(ProductQuery(query="wind speed", status="ALL"))
    assert [r.product_code for r, *_ in wind.items][:2] == ["DP1.00001.001", "DP1.00007.001"]
    assert "name" in wind.items[0][2]
    assert (
        rest_products.search(ProductQuery(query="DP1.10003")).items[0][0].product_code
        == "DP1.10003.001"
    )
    assert [
        r.product_code for r, *_ in rest_products.search(ProductQuery(science_team="TOS")).items
    ] == ["DP1.10003.001"]
    assert rest_products.search(ProductQuery(site_code="ABBY")).total >= 1
    assert rest_products.search(ProductQuery(level=1, has_expanded=True)).total >= 1
    assert rest_products.search(ProductQuery(theme="atmo")).total >= 1
    sorted_names = rest_products.search(ProductQuery(sort="productName"))
    names = [r.product_name.lower() for r, *_ in sorted_names.items]
    assert names == sorted(names)


def test_did_you_mean_and_facets(rest_products: ProductIndex) -> None:
    typo = rest_products.search(ProductQuery(query="breeeding"))
    assert typo.items[0][0].product_code == "DP1.10003.001"  # typo tolerance
    miss = rest_products.search(ProductQuery(query="landbirds xyzzy"))
    assert miss.total == 0 and miss.did_you_mean and "landbird" in miss.did_you_mean
    facets = ProductIndex.facets(rest_products.records)
    assert facets["productStatus"] == {"ACTIVE": 5, "FUTURE": 1}
    assert set(facets["scienceTeams"]) == {"AIS", "AOP", "AOS", "TIS", "TOS"}


def test_spec_lookup(rest_products: ProductIndex) -> None:
    spec, codes = rest_products.spec_lookup("NEON.DOC.000780vD")
    assert spec is not None and spec.spec_size == 715529 and codes == ["DP1.00001.001"]
    assert rest_products.spec_lookup("NEON.DOC.000000vA") == (None, [])


def test_site_search_nearest_and_fuzzy(rest_sites: SiteIndex) -> None:
    harv = rest_sites.by_code("harv")
    assert harv is not None
    found = rest_sites.search(SiteQuery(query="Harvard"))
    assert found.items[0][0].site_code == "HARV"
    near = rest_sites.nearest(harv.latitude, harv.longitude, 10)  # type: ignore[arg-type]
    assert near[0][0].site_code == "HARV" and near[0][1] == 0.0
    prox = rest_sites.search(
        SiteQuery(latitude=harv.latitude, longitude=harv.longitude, radius_km=5000)
    )
    assert prox.items[0][0].site_code == "HARV"
    assert rest_sites.fuzzy_candidates("Harvard Forest")[0].code == "HARV"
    assert rest_sites.fuzzy_candidates("abby")[0].score == 1.0
    assert SiteIndex.facets(rest_sites.records)["siteTypes"]
    assert rest_sites.domains()["D01"]
    assert rest_sites.domain_sites("D01") == frozenset({"HARV"})
    assert rest_sites.search(SiteQuery(query="zzzqqq")).total == 0


async def test_catalog_uses_graphql_and_caches(server: NeonServer, router: FixtureRouter) -> None:
    first = await server.catalog.products()
    second = await server.catalog.products()
    assert first is second and first.source == "graphql"
    assert router.paths() == ["POST graphql:NeonMcpProductsCatalog"]
    assert server.catalog.warmth().products == "warm"


async def test_drift_falls_back_to_rest(server: NeonServer, router: FixtureRouter) -> None:
    router.drift_catalog = True
    index = await server.catalog.products()
    assert index.source == "rest" and len(index) == 6
    assert router.paths() == ["POST graphql:NeonMcpProductsCatalog", "GET /products"]
    assert server.catalog.warmth().graphql_fallbacks == 1


async def test_breaker_opens_after_repeated_failures(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.fail_graphql = True
    await server.catalog.products()
    await server.catalog.sites()
    assert server.catalog.warmth().breaker_open
    router.reset()
    rows, via = await server.catalog.product_availability(["DP1.00001.001"])
    assert via == "rest" and not any(c.path.startswith("graphql") for c in router.calls)
    assert rows[0]["siteCodes"][0]["siteCode"] == "ABBY"


async def test_unknown_release_surfaces_rest_error(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.add(
        Route(
            "POST",
            "graphql:NeonMcpProductsCatalog",
            Reply(
                json={
                    "errors": [
                        {
                            "message": "Exception while fetching data (/products) : Release not found."
                        }
                    ],
                    "data": {"products": None},
                }
            ),
            body=lambda b: b["variables"]["release"] == "RELEASE-1999",
        )
    )
    with pytest.raises(NeonApiError) as exc:
        await server.catalog.products(release="RELEASE-1999")
    assert exc.value.data["validReleases"]
    assert (
        server.catalog.warmth().graphql_fallbacks == 0 and not server.catalog.warmth().breaker_open
    )


async def test_availability_graphql_and_rest(server: NeonServer, router: FixtureRouter) -> None:
    rows, via = await server.catalog.product_availability(
        ["DP1.00001.001"], site_codes=["ABBY"], start="2023-01", end="2023-06"
    )
    assert via == "graphql" and rows[0]["productCode"] == "DP1.00001.001"
    sent = router.calls[-1].body["variables"]["filter"]
    assert sent == {
        "productCodes": ["DP1.00001.001"],
        "siteCodes": ["ABBY"],
        "startMonth": "2023-01",
        "endMonth": "2023-06",
    }
    site_rows, site_via = await server.catalog.site_availability(
        ["ABBY"], product_codes=["DP1.00001.001"]
    )
    assert site_via == "graphql" and site_rows[0]["siteCode"] == "ABBY"
    router.fail_graphql = True
    server.catalog.config.neon.graphql_breaker_failures = 99
    rest_rows, rest_via = await server.catalog.site_availability(
        ["ABBY"], product_codes=["DP1.00001.001"], start="2026-01", end="2026-12"
    )
    assert rest_via == "rest"
    months = rest_rows[0]["dataProducts"][0]["availableMonths"]
    assert all("2026-01" <= m <= "2026-12" for m in months)


async def test_locations_batch_fallback_marks_failures(
    server: NeonServer, router: FixtureRouter
) -> None:
    rows, via = await server.catalog.locations_batch(["HARV", "TOWER104454", "D01"])
    assert via == "graphql" and len(rows) == 3
    router.fail_graphql = True
    rows, via = await server.catalog.locations_batch(["HARV", "NOPE_NOT_A_LOCATION"])
    assert via == "rest"
    by_name: dict[str, Any] = {r["locationName"]: r for r in rows}
    assert by_name["HARV"]["locationType"] == "SITE"
    assert by_name["NOPE_NOT_A_LOCATION"]["detailError"]["code"] == "not_found"
    assert await server.catalog.locations_batch([]) == ([], "graphql")


async def test_lists_and_prewarm(server: NeonServer, router: FixtureRouter) -> None:
    assert await server.catalog.prewarm() is True
    warmth = server.catalog.warmth()
    assert (warmth.products, warmth.sites, warmth.source) == ("warm", "warm", "graphql")
    assert server.catalog.peek_sites() is not None and server.catalog.peek_products() is not None
    assert len(await server.catalog.releases()) == 2
    assert len(await server.catalog.prototype_datasets()) == 3
    assert len(await server.catalog.sample_classes()) == 8
    assert len(await server.catalog.site_locations()) == 3
    sites = await server.catalog.sites_for_release("RELEASE-2026")
    assert sites is not None and sites[0]["siteCode"] == "ABBY"


async def test_prewarm_degrades_when_everything_fails(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.inject_5xx(20)
    assert await server.catalog.prewarm() is False
    assert server.catalog.warmth().products == "degraded"
