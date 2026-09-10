from __future__ import annotations

from neon_mcp.errors import NeonApiError, map_api_error
from neon_mcp.server import NeonServer
from tests.fixture_router import ANY, FixtureRouter, Reply, Route, load_fixture
from tests.helpers import call_err, call_ok


async def test_type_code_paging(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_search_taxonomy", {"taxon_type_code": "bird", "limit": 5})
    assert router.calls[0].params == {
        "taxonTypeCode": "BIRD",
        "verbose": "false",
        "offset": "0",
        "limit": "5",
    }
    assert [i["dwc:scientificName"] for i in payload["items"]][:2] == [
        "Anas rubripes",
        "Muscicapa dauurica",
    ]
    assert len(payload["items"][0]) == 17 and payload["items"][0]["gbif:subspecies"] is None
    assert payload["page"] == {
        "total": 2244,
        "returned": 5,
        "offset": 0,
        "limit": 5,
        "truncated": True,
        "nextOffset": 5,
        "truncatedReason": "limit",
    }
    assert payload["filters"] == {"taxonTypeCode": "BIRD"} and "offset=5" in payload["nextSteps"][0]
    await call_ok(server, "neon_search_taxonomy", {"taxon_type_code": "BIRD", "limit": 5})
    assert len(router.calls) == 1  # cached


async def test_verbose_drops_null_ranks_and_caps(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(
        server, "neon_search_taxonomy", {"taxon_type_code": "BIRD", "verbose": True, "limit": 2}
    )
    assert len(payload["items"][0]) == 24 and None not in payload["items"][0].values()
    router.add(
        Route(
            "GET",
            "/taxonomy",
            Reply(fixture="taxonomy_BIRD_verbose.json"),
            params={"taxonTypeCode": "BIRD", "verbose": "true", "offset": "0", "limit": "100"},
        )
    )
    capped = await call_ok(
        server, "neon_search_taxonomy", {"taxon_type_code": "BIRD", "verbose": True, "limit": 400}
    )
    assert capped["page"]["limit"] == 100 and any("capped" in n for n in capped["notes"])


async def test_rank_filters_and_genus_fallback(server: NeonServer, router: FixtureRouter) -> None:
    genus = await call_ok(server, "neon_search_taxonomy", {"genus": "Quercus", "limit": 5})
    assert len(genus["items"]) == 5 and genus["page"]["nextOffset"] == 5
    fallback = await call_ok(
        server, "neon_search_taxonomy", {"scientificName": "Quercus agrifolia", "limit": 5}
    )
    assert fallback["fuzzyFallbackUsed"] is True
    assert [i["dwc:scientificName"] for i in fallback["items"]] == ["Quercus agrifolia Née"]
    assert fallback["page"]["truncated"] is False
    assert [c.params.get("scientificname") or c.params.get("genus") for c in router.calls[-2:]] == [
        "Quercus agrifolia",
        "Quercus",
    ]
    router.add(
        Route(
            "GET",
            "/taxonomy",
            Reply(fixture="taxonomy_BIRD_p1.json"),
            params={"class": "Aves", "verbose": "false", "offset": "0", "limit": ANY},
        )
    )
    aves = await call_ok(server, "neon_search_taxonomy", {"class": "Aves", "limit": 5})
    assert aves["filters"] == {"class": "Aves"}


async def test_validation_prevents_calls(server: NeonServer, router: FixtureRouter) -> None:
    err = await call_err(
        server,
        "neon_search_taxonomy",
        {"taxon_type_code": "BIRD", "genus": "Anas"},
        "invalid_argument",
    )
    assert "must not both be specified" in err["message"]
    await call_err(server, "neon_search_taxonomy", {}, "invalid_argument")
    await call_err(
        server, "neon_search_taxonomy", {"taxon_type_code": "DRAGON"}, "invalid_argument"
    )
    assert router.calls == []


def test_upstream_conflict_maps_to_invalid_argument() -> None:
    body = load_fixture("taxonomy_400_conflict.json")
    err = map_api_error(NeonApiError(400, body["error"]["detail"], "/taxonomy"))
    assert err.code == "invalid_argument"
