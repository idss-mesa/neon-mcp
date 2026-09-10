"""Whole-system checks: coverage of tools by tests, endpoint reachability, end-to-end trace."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from neon_mcp.registry import get_registered_tools
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter, Reply, Route
from tests.helpers import call_ok

ROOT = Path(__file__).resolve().parents[1]

#: Every NEON path neon-mcp calls (DESIGN.md 1.2 reachability matrix).
REACHED = {
    "GET /products",
    "GET /products/{productCode}",
    "GET /sites",
    "GET /sites/{siteCode}",
    "GET /locations/sites",
    "GET /locations/{locationName}",
    "GET /data/{productCode}/{siteCode}/{yearMonth}",
    "GET /data/{productCode}/{siteCode}/{yearMonth}/{filename}",
    "GET /data/package/{productCode}/{siteCode}/{yearMonth}",
    "POST /data/query",
    "GET /releases",
    "GET /releases/{releaseIdentifier}",
    "GET /releases/{releaseTag}/products/{productCode}",
    "GET /releases/{releaseTag}/sites/{siteCode}",
    "GET /samples/supportedClasses",
    "GET /samples/classes",
    "GET /samples/view",
    "GET /samples/download",
    "GET /taxonomy",
    "GET /prototype/datasets",
    "GET /prototype/datasets/{uuid}",
    "GET /prototype/data/{uuid}",
    "GET /documents/{specNumber}",
    "POST /graphql",
}
#: Swagger 0.11.0 paths deliberately never called.
DOCUMENTED_UNUSED = {
    "GET /data/query",  # identical to POST /data/query
    "GET /releases/{releaseTag}/products",  # 25.8 MB; release products come from /releases/{tag}
    "GET /releases/{releaseTag}/sites",  # 22.2 MB; release sites come from GraphQL
    "GET /releases/{releaseTag}/data/{productCode}/{siteCode}/{yearMonth}",  # ?release= on /data is equivalent
    "GET /prototype/data/{uuid}/{filename}",  # the dataset listing already carries signed file URLs
}


def test_endpoint_reachability_matrix() -> None:
    declared = {e for spec in get_registered_tools() for e in spec.endpoints}
    assert declared == REACHED
    assert not declared & DOCUMENTED_UNUSED


def test_every_tool_has_unit_and_live_tests() -> None:
    unit = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "tests").rglob("test_*.py")
        if "live" not in p.parts and p.name != "test_integration_meta.py"
    )
    live = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "tests" / "live").glob("test_*.py")
    )
    for spec in get_registered_tools():
        assert re.search(rf'"{spec.name}"', unit), f"no unit test calls {spec.name}"
        assert re.search(rf'"{spec.name}"', live), f"no live test calls {spec.name}"


def test_token_and_transport_sets() -> None:
    specs = get_registered_tools()
    assert {s.name for s in specs if s.requires_token} == {
        "neon_list_files",
        "neon_download_files",
        "neon_get_sample",
    }
    assert [s.name for s in specs if "http" not in s.transports] == ["neon_download_files"]
    assert len(specs) == 20


CSV = b"namedLocation,pointID,count\nHARV_025.birdGrid.brd,A1,3\n"
NAMES = (
    "NEON.D01.HARV.DP1.10003.001.brd_countdata.2023-06.basic.20250128T000000Z.csv",
    "NEON.D01.HARV.DP1.10003.001.brd_perpoint.2023-06.basic.20250128T000000Z.csv",
    "NEON.D01.HARV.DP1.10003.001.readme.20250128T000000Z.txt",
)


async def test_design_trace_five_calls(token_server: NeonServer, router: FixtureRouter) -> None:
    """DESIGN.md Appendix B: search -> availability -> files -> download -> cite."""
    files = [
        {
            "name": n,
            "size": len(CSV),
            "md5": hashlib.md5(CSV).hexdigest(),  # noqa: S324
            "url": f"https://storage.googleapis.com/fixture/{i}",
        }
        for i, n in enumerate(NAMES)
    ]
    router.add(
        Route(
            "GET",
            "/data/DP1.10003.001/HARV/2023-06",
            Reply(
                json={
                    "data": {
                        "productCode": "DP1.10003.001",
                        "siteCode": "HARV",
                        "month": "2023-06",
                        "release": "RELEASE-2026",
                        "packages": [],
                        "files": files,
                        "externalData": [],
                    }
                }
            ),
            params={"package": "basic"},
            token=True,
        )
    )
    for i in range(3):
        router.add(
            Route(
                "GET",
                f"https://storage.googleapis.com/fixture/{i}",
                Reply(content=CSV, content_type="text/csv"),
            )
        )

    found = await call_ok(
        token_server, "neon_search_products", {"query": "breeding bird point counts"}
    )
    code = found["items"][0]["productCode"]
    assert code == "DP1.10003.001"
    avail = await call_ok(
        token_server, "neon_get_availability", {"product": code, "domain_code": "D01"}
    )
    assert [r["siteCode"] for r in avail["rows"]] == ["HARV"] and "PROVISIONAL" in avail["rows"][0][
        "byRelease"
    ]
    listing = await call_ok(
        token_server,
        "neon_list_files",
        {
            "product": code,
            "site_codes": ["Harvard Forest"],
            "start_month": "2023-06",
            "kind": "data",
        },
    )
    assert listing["resolved"][0]["code"] == "HARV" and len(listing["files"]) == 2
    report = await call_ok(
        token_server,
        "neon_download_files",
        {"product": code, "site_codes": ["HARV"], "start_month": "2023-06", "kind": "data"},
    )
    assert [f["status"] for f in report["files"]] == ["downloaded", "downloaded"]
    assert all(f["md5Verified"] for f in report["files"]) and report["nextSteps"][0].startswith(
        "pandas.read_csv"
    )
    cite = await call_ok(token_server, "neon_get_citation", {"product": code})
    assert cite["doi"] == "10.48443/v6hs-mx57"
