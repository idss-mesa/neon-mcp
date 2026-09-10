from __future__ import annotations

import json

import pytest
from typing import get_args

from neon_mcp.errors import ToolError
from neon_mcp.models.common import FileKind, TaxonTypeCode
from neon_mcp.resources import (
    DERIVED_TTL_MS,
    STATIC_TTL_MS,
    citation_templates,
    list_resource_templates,
    list_resources,
    read_resource,
)
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter


def test_listing_is_sorted_and_tagged() -> None:
    resources = list_resources()
    uris = [str(r.uri) for r in resources]
    assert uris == sorted(uris) and len(uris) == 8
    kinds = {str(r.uri): (r.meta or {})["io.neon-mcp/kind"] for r in resources}
    assert (
        kinds["neon://reference/sites"] == "derived" and kinds["neon://guide/api-token"] == "static"
    )
    assert [t.uri_template for t in list_resource_templates()] == [
        "neon://products/{productCode}",
        "neon://sites/{siteCode}",
        "neon://releases/{release}",
    ]


async def test_static_reads(server: NeonServer, router: FixtureRouter) -> None:
    ctx = server.tool_context("resources/read")
    for resource in list_resources():
        if (resource.meta or {}).get("io.neon-mcp/kind") != "static":
            continue
        content = await read_resource(str(resource.uri), ctx)
        assert content.ttl_ms == STATIC_TTL_MS and content.text.strip()
        if content.mime_type == "application/json":
            json.loads(content.text)
    assert router.calls == []


async def test_derived_and_templates(server: NeonServer) -> None:
    ctx = server.tool_context("resources/read")
    sites = json.loads((await read_resource("neon://reference/sites", ctx)).text)
    assert sites["count"] == 3 and sites["sites"][0]["siteCode"] == "ABBY"
    releases = await read_resource("neon://reference/releases", ctx)
    assert (
        releases.ttl_ms == DERIVED_TTL_MS
        and json.loads(releases.text)["latestRelease"] == "RELEASE-2026"
    )
    product = json.loads((await read_resource("neon://products/DP1.00001.001", ctx)).text)
    assert product["productCode"] == "DP1.00001.001"
    site = json.loads((await read_resource("neon://sites/HARV", ctx)).text)
    assert site["siteCode"] == "HARV" and site["dataProducts"]
    release = json.loads((await read_resource("neon://releases/RELEASE-2025", ctx)).text)
    assert release["release"] == "RELEASE-2025"
    with pytest.raises(ToolError) as exc:
        await read_resource("neon://guide/nope", ctx)
    assert exc.value.code == "not_found" and exc.value.details["didYouMean"]
    with pytest.raises(ToolError) as bad:
        await read_resource("neon://products/DP9.99999.999", ctx)
    assert bad.value.code == "not_found"


def test_citation_templates_parse() -> None:
    t = citation_templates()
    assert "$doiUrl" in t.released and "provisional data" in t.provisional
    assert "$uuid" in t.prototype and t.bibtex.startswith("@misc{$key,")


def test_vocabularies_cover_input_enums() -> None:
    from neon_mcp.resources import _static_text

    vocab = json.loads(_static_text("vocabularies.json"))
    assert set(vocab["taxonTypeCodes"]) == set(get_args(get_args(TaxonTypeCode)[0]))
    assert set(vocab["fileKinds"]) == set(get_args(FileKind))
    assert len(vocab["domains"]) == 20 and {"TOWER", "SITE", "DOMAIN"} <= set(
        vocab["locationTypes"]
    )
    assert set(vocab["scienceTeams"]) == {"AIS", "AOP", "AOS", "TIS", "TOS"}
