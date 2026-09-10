from __future__ import annotations

from typing import Any

import pytest

from neon_mcp.errors import ToolError
from neon_mcp.neon.catalog import ProductIndex, SiteIndex, product_record, site_record
from neon_mcp.neon.resolve import _decide, resolve_product, resolve_site, resolve_sites
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter


async def test_exact_codes_take_the_fast_path(server: NeonServer, router: FixtureRouter) -> None:
    ctx = server.tool_context("t")
    assert await resolve_product("DP1.10003.001", ctx) == ("DP1.10003.001", None)
    assert await resolve_product("dp1.10003", ctx) == ("DP1.10003.001", None)
    assert await resolve_product("NEON.DOM.SITE.DP1.00001.001", ctx) == ("DP1.00001.001", None)
    assert await resolve_site("harv", ctx) == ("HARV", None)
    assert router.calls == []


async def test_fuzzy_product_accept_ambiguous_and_missing(server: NeonServer) -> None:
    ctx = server.tool_context("t")
    code, resolved = await resolve_product("breeding landbird", ctx)
    assert code == "DP1.10003.001"
    assert resolved is not None and resolved.field == "product" and resolved.confidence >= 0.9
    with pytest.raises(ToolError) as amb:
        await resolve_product("wind speed direction", ctx)
    assert amb.value.code == "ambiguous_input"
    assert {c["code"] for c in amb.value.details["candidates"]} >= {
        "DP1.00001.001",
        "DP1.00007.001",
    }
    with pytest.raises(ToolError) as missing:
        await resolve_product("zzzz qqqq xxxx", ctx)
    assert missing.value.code == "not_found" and "didYouMean" in missing.value.details


async def test_fuzzy_sites_and_dedupe(server: NeonServer) -> None:
    ctx = server.tool_context("t")
    code, resolved = await resolve_site("Harvard Forest", ctx, field="site_codes")
    assert code == "HARV" and resolved is not None and resolved.field == "site_codes"
    codes, echoes = await resolve_sites(["HARV", "Harvard Forest", "abby"], ctx)
    assert codes == ["HARV", "ABBY"] and len(echoes) == 1
    with pytest.raises(ToolError) as exc:
        await resolve_site("MOAB", ctx)  # 4 letters, catalog now warm, not a site
    assert exc.value.code in ("not_found", "ambiguous_input")


def _site(code: str, name: str) -> Any:
    return site_record({"siteCode": code, "siteName": name, "stateName": "X", "domainCode": "D01"})


def test_adversarial_site_names_do_not_resolve() -> None:
    index = SiteIndex(
        [
            _site("BLUE", "Blue River NEON"),
            _site("ORNL", "Oak Ridge NEON"),
            _site("NIWO", "Niwot Ridge NEON"),
        ],
        source="rest",
        release=None,
        built_at=0,
    )
    with pytest.raises(ToolError) as exc:
        _decide(index.fuzzy_candidates("Blue Ridge"), field="site", value="Blue Ridge", kind="site")
    assert exc.value.code == "ambiguous_input"
    assert (
        _decide(index.fuzzy_candidates("Oak Ridge"), field="site", value="Oak Ridge", kind="site")[
            0
        ]
        == "ORNL"
    )


def test_exact_name_beats_close_runner_up() -> None:
    index = ProductIndex(
        [
            product_record({"productCode": "DP1.00041.001", "productName": "Soil temperature"}),
            product_record(
                {
                    "productCode": "DP2.00006.001",
                    "productName": "Temporally interpolated soil temperature",
                }
            ),
        ],
        source="rest",
        release=None,
        built_at=0,
    )
    code, resolved = _decide(
        index.fuzzy_candidates("soil temperature"),
        field="product",
        value="soil temperature",
        kind="product",
    )
    assert code == "DP1.00041.001" and resolved.confidence == 1.0
