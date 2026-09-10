"""One live test per tool (DESIGN.md 8.3); run with NEON_MCP_LIVE=1. Serial, about 30 requests."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from neon_mcp.server import NeonServer
from tests.fixture_router import PROTOTYPE_UUID, load_fixture
from tests.helpers import call_ok

pytestmark = pytest.mark.live


async def test_ping(live: NeonServer) -> None:
    payload = await call_ok(live, "neon_ping", {"check_api": True})
    assert payload["api"]["reachable"] is True and payload["api"]["status"] == 200
    assert payload["rateLimit"]["limit"] in (200, 2000)


async def test_search_and_get_product(live: NeonServer) -> None:
    found = await call_ok(live, "neon_search_products", {"query": "breeding bird"})
    assert "DP1.10003.001" in [i["productCode"] for i in found["items"]]
    detail = await call_ok(
        live, "neon_get_product", {"product": "DP1.00001.001", "include": ["specs", "availability"]}
    )
    assert detail["specs"] and detail["availability"]["siteCount"] >= 40
    raw_keys = set(load_fixture("product_DP1.00001.001.json")["data"])
    upstream = await live.client.get_json("/products/DP1.00001.001", token=None)
    assert raw_keys <= set(upstream.data), "upstream schema drift in /products/{code}"


async def test_availability_graphql_matches_rest(live: NeonServer) -> None:
    payload = await call_ok(
        live, "neon_get_availability", {"product": "DP1.00001.001", "site_codes": ["HARV"]}
    )
    gql_months = payload["rows"][0]["monthCount"]
    rest = await live.client.get_json("/products/DP1.00001.001", token=None)
    harv = next(s for s in rest.data["siteCodes"] if s["siteCode"] == "HARV")
    rest_months = len({m for r in harv["availableReleases"] for m in r["availableMonths"]})
    assert gql_months == rest_months


async def test_sites(live: NeonServer) -> None:
    found = await call_ok(live, "neon_search_sites", {"query": "Harvard"})
    assert found["items"][0]["siteCode"] == "HARV"
    site = await call_ok(live, "neon_get_site", {"site": "HARV"})
    assert len(site["dataProducts"]) >= 50


async def test_locations(live: NeonServer) -> None:
    towers = await call_ok(
        live, "neon_find_locations", {"site_codes": ["HARV"], "location_type": "TOWER"}
    )
    assert "TOWER100450" in [i["locationName"] for i in towers["items"]]
    domains = await call_ok(
        live,
        "neon_find_locations",
        {"root": "REALM", "location_type": "DOMAIN", "include_coordinates": False},
    )
    assert domains["page"]["total"] == 20
    loc = await call_ok(live, "neon_get_location", {"name": "HARV", "include": ["hierarchy"]})
    assert [p["locationName"] for p in loc["parentChain"]][:1] == ["D01"]


async def test_releases_and_citation(live: NeonServer) -> None:
    releases = await call_ok(live, "neon_list_releases", {})
    assert "RELEASE-2026" in [r["release"] for r in releases["items"]]
    release = await call_ok(
        live, "neon_get_release", {"release": "RELEASE-2026", "include": ["sites"]}
    )
    assert len(release["sites"]) >= 80
    cite = await call_ok(
        live, "neon_get_citation", {"product": "DP1.10003.001", "release": "RELEASE-2026"}
    )
    assert cite["doi"] == "10.48443/v6hs-mx57"


async def test_taxonomy_samples_prototype(live: NeonServer) -> None:
    taxa = await call_ok(live, "neon_search_taxonomy", {"taxon_type_code": "BIRD", "limit": 2})
    assert taxa["page"]["total"] > 1000 and "dwc:scientificName" in taxa["items"][0]
    classes = await call_ok(live, "neon_list_sample_classes", {"query": "bet"})
    assert classes["items"]
    protos = await call_ok(live, "neon_search_prototype_datasets", {"query": "reaeration"})
    assert PROTOTYPE_UUID in [i["uuid"] for i in protos["items"]]
    proto = await call_ok(live, "neon_get_prototype_dataset", {"uuid": PROTOTYPE_UUID})
    assert proto["files"]


async def test_document_and_graphql(live: NeonServer) -> None:
    doc = await call_ok(live, "neon_get_document", {"spec_number": "NEON.DOC.000780vD"})
    assert doc["contentType"] == "application/pdf" and doc["size"]
    gql = await call_ok(live, "neon_graphql", {"introspect_type": "Site"})
    assert gql["data"]["__type"]["name"] == "Site"


async def test_tools_list_size_is_within_bound(live: NeonServer) -> None:
    body = {
        "tools": [t.model_dump(by_alias=True, exclude_none=True) for t in live.tool_definitions()]
    }
    assert len(json.dumps(body, separators=(",", ":"))) <= live.config.limits.tools_list_max_bytes


async def test_data_files_and_download(live: NeonServer, needs_token: None) -> None:
    one = await call_ok(
        live,
        "neon_list_files",
        {
            "product": "DP1.00001.001",
            "site_codes": ["HARV"],
            "start_month": "2023-06",
            "kind": "readme",
        },
    )
    assert one["files"] and one["urlExpiresAt"]
    wide = await call_ok(
        live,
        "neon_list_files",
        {
            "product": "DP1.00001.001",
            "site_codes": ["HARV", "ABBY"],
            "start_month": "2023-05",
            "end_month": "2023-06",
            "detail": "summary",
        },
    )
    assert wide["summary"]["siteMonthsWithData"] >= 3
    report = await call_ok(
        live,
        "neon_download_files",
        {
            "product": "DP1.00001.001",
            "site_codes": ["HARV"],
            "start_month": "2023-06",
            "kind": "readme",
        },
    )
    assert report["files"][0]["status"] == "downloaded"


async def test_sample(live: NeonServer, needs_token: None) -> None:
    barcode = os.environ.get("NEON_MCP_LIVE_SAMPLE_BARCODE")
    if not barcode:
        pytest.skip("set NEON_MCP_LIVE_SAMPLE_BARCODE to a real sample barcode")
    payload: dict[str, Any] = await call_ok(live, "neon_get_sample", {"barcode": barcode})
    assert payload["items"]
