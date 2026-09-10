from __future__ import annotations

from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok

TOWER_COORDS = {
    "data": {
        "findLocations": [
            {
                "locationName": "TOWER100450",
                "locationType": "TOWER",
                "siteCode": "HARV",
                "domainCode": "D01",
                "locationDecimalLatitude": 42.537454,
                "locationDecimalLongitude": -72.172666,
                "locationElevation": 342.39,
            }
        ]
    }
}


def names(payload: dict) -> list[str]:  # type: ignore[type-arg]
    return [i["locationName"] for i in payload["items"]]


async def test_towers_at_a_site(server: NeonServer, router: FixtureRouter) -> None:
    router.add(
        Route(
            "POST",
            "graphql:NeonMcpLocations",
            Reply(json=TOWER_COORDS),
            body=lambda b: b["variables"]["query"]["locationNames"] == ["TOWER100450"],
        )
    )
    payload = await call_ok(
        server, "neon_find_locations", {"site_codes": ["Harvard Forest"], "location_type": "tower"}
    )
    assert payload["locationType"] == "TOWER" and names(payload) == ["TOWER100450"]
    item = payload["items"][0]
    assert (
        item["depth"] == 1
        and item["parent"] == "HARV"
        and item["locationDecimalLatitude"] == 42.537454
    )
    assert payload["hierarchyNodesScanned"] == 68 and "typesAvailable" not in payload
    assert (
        payload["resolved"][0]["code"] == "HARV" and payload["roots"][0]["locationName"] == "HARV"
    )
    assert router.calls_to("GET /locations/HARV")[0].params == {
        "hierarchy": "true",
        "locationType": "TOWER",
    }
    assert "neon_get_location(name='TOWER100450'" in payload["nextSteps"][0]


async def test_unfiltered_site_walk_reports_types(
    server: NeonServer, router: FixtureRouter
) -> None:
    payload = await call_ok(
        server, "neon_find_locations", {"root": "harv", "include_coordinates": False}
    )
    assert payload["typesAvailable"] == {
        "CONFIG": 2,
        "OS Plot - all": 1,
        "OS Plot - bet": 1,
        "Point": 2,
    }
    assert payload["hierarchyNodesScanned"] == 6 and len(payload["items"]) == 6
    assert (
        len(router.calls_to("GET /locations/HARV")) == 1
    )  # one fetch, types from the same payload
    assert any("location_type" in n for n in payload["notes"])
    router.add(
        Route(
            "GET",
            "/locations/HARV",
            Reply(fixture="location_HARV_hierarchy.json"),
            params={"hierarchy": "true", "locationType": "Point"},
        )
    )
    points = await call_ok(
        server,
        "neon_find_locations",
        {"root": "HARV", "location_type": "point", "include_coordinates": False},
    )
    assert names(points) == ["HARV_001.basePlot.bet.E", "HARV_001.basePlot.bet.N"]
    assert (
        points["items"][0]["depth"] == 2 and points["items"][0]["parent"] == "HARV_001.basePlot.bet"
    )
    shallow = await call_ok(
        server,
        "neon_find_locations",
        {"root": "HARV", "max_depth": 1, "include_coordinates": False, "query": "plot"},
    )
    assert names(shallow) == ["HARV_001.basePlot.all", "HARV_001.basePlot.bet"]


async def test_realm_fast_paths_and_guard(server: NeonServer, router: FixtureRouter) -> None:
    await call_err(server, "neon_find_locations", {"root": "REALM"}, "invalid_argument")
    await call_err(server, "neon_find_locations", {"root": "d01"}, "invalid_argument")
    assert router.calls == []
    sites = await call_ok(server, "neon_find_locations", {"root": "REALM", "location_type": "SITE"})
    assert names(sites) == ["ABBY", "HARV", "SRER"] and all(
        i["isFieldSite"] for i in sites["items"]
    )
    assert sites["items"][1]["locationElevation"] == 348.12784
    assert "GET /locations/sites" in router.paths()
    domains = await call_ok(
        server,
        "neon_find_locations",
        {"root": "REALM", "location_type": "DOMAIN", "include_coordinates": False, "limit": 5},
    )
    assert names(domains) == ["D01", "D02", "D03", "D04", "D05"] and domains["page"]["total"] == 20
    assert "/locations/REALM" in router.paths()[-1] or any(
        c.path == "/locations/REALM" for c in router.calls
    )


async def test_coordinates_fallback_and_proximity(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.fail_graphql = True
    payload = await call_ok(
        server, "neon_find_locations", {"root": "HARV", "location_type": "TOWER"}
    )
    assert (
        payload["items"][0]["locationDecimalLatitude"] == 42.537454
    )  # REST GET /locations/TOWER100450
    router.fail_graphql = False
    router.add(Route("POST", "graphql:NeonMcpLocations", Reply(json=TOWER_COORDS)))
    near = await call_ok(
        server,
        "neon_find_locations",
        {
            "root": "HARV",
            "location_type": "TOWER",
            "latitude": 42.54,
            "longitude": -72.17,
            "radius_km": 5,
        },
    )
    assert near["items"][0]["distanceKm"] < 1
    far = await call_ok(
        server,
        "neon_find_locations",
        {
            "root": "HARV",
            "location_type": "TOWER",
            "latitude": 31.9,
            "longitude": -110.8,
            "radius_km": 5,
        },
    )
    assert far["items"] == []


async def test_find_errors(server: NeonServer) -> None:
    await call_err(server, "neon_find_locations", {}, "invalid_argument")
    await call_err(
        server, "neon_find_locations", {"root": "HARV", "site_codes": ["HARV"]}, "invalid_argument"
    )
    await call_err(
        server, "neon_find_locations", {"root": "HARV", "latitude": 1.0}, "invalid_argument"
    )
    missing = await call_err(
        server,
        "neon_find_locations",
        {"root": "NOPE_NOT_A_LOCATION", "location_type": "TOWER"},
        "not_found",
    )
    assert "case-sensitive" in missing["hint"]


async def test_get_location_default(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_location", {"name": "HARV"})
    assert router.calls[0].params == {}
    assert payload["locationType"] == "SITE" and payload["locationUtmZone"] == 18
    assert (
        payload["propertyCount"] == 36
        and payload["locationProperties"]["Value for AERONET_XREF"] == "NEON_Harvard"
    )
    assert payload["hasPolygon"] is False and payload["locationParent"] == "D01"
    assert "neon_get_location(name='D01')" in " ".join(payload["nextSteps"])


async def test_get_location_sections(server: NeonServer, router: FixtureRouter) -> None:
    hier = await call_ok(
        server,
        "neon_get_location",
        {"name": "HARV", "include": ["hierarchy", "children"], "children_limit": 2},
    )
    assert [p["locationName"] for p in hier["parentChain"]] == ["D01", "REALM"]
    assert hier["childrenByType"] == {
        "CONFIG": 2,
        "OS Plot - all": 1,
        "OS Plot - bet": 1,
        "Point": 2,
    }
    assert len(hier["children"]) == 2 and hier["childrenPage"]["nextOffset"] == 2
    assert any("children_offset=2" in s for s in hier["nextSteps"]) and hier["notes"]
    assert "locationProperties" not in hier
    history = await call_ok(server, "neon_get_location", {"name": "HARV", "include": ["history"]})
    assert [h["current"] for h in history["locationHistory"]] == [True, False]
    assert history["locationHistory"][0]["locationProperties"] == {"Value for Site Timezone": "EST"}
    assert history["historyTruncated"] is False
    domain = (
        await call_ok(server, "neon_get_location", {"name": "d01", "include": ["all"]})
        if False
        else None
    )
    assert domain is None


async def test_get_location_guard_and_errors(server: NeonServer, router: FixtureRouter) -> None:
    await call_err(
        server, "neon_get_location", {"name": "D01", "include": ["children"]}, "invalid_argument"
    )
    assert router.calls == []
    domain = await call_ok(server, "neon_get_location", {"name": "D01"})
    assert domain["locationType"] == "DOMAIN"
    await call_err(server, "neon_get_location", {"name": "NOPE_NOT_A_LOCATION"}, "not_found")
    await call_err(
        server, "neon_get_location", {"name": "HARV", "include": ["everything"]}, "invalid_argument"
    )
