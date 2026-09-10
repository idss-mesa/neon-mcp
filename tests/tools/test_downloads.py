from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from neon_mcp.server import NeonServer
from tests.fixture_router import PROTOTYPE_UUID, TEST_TOKEN, FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok

WIND = "DP1.00001.001"
A = b"a,b\n1,2\n" * 200
B = b"readme text\n" * 50
NAMES = (
    "NEON.D16.ABBY.DP1.00001.001.000.010.030.2DWSD_30min.2023-03.basic.20250128T000000Z.csv",
    "NEON.D16.ABBY.DP1.00001.001.readme.20250128T000000Z.txt",
)
URLS = (
    "https://storage.googleapis.com/fixture/a.csv",
    "https://storage.googleapis.com/fixture/b.txt",
)


def md5(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()  # noqa: S324


def listing_routes(router: FixtureRouter, *, bad_md5: bool = False) -> None:
    files = [
        {"name": NAMES[0], "size": len(A), "md5": "f" * 32 if bad_md5 else md5(A), "url": URLS[0]},
        {"name": NAMES[1], "size": len(B), "md5": md5(B), "url": URLS[1]},
    ]
    router.add(
        Route(
            "GET",
            f"/data/{WIND}/ABBY/2023-03",
            Reply(
                json={
                    "data": {
                        "productCode": WIND,
                        "siteCode": "ABBY",
                        "month": "2023-03",
                        "release": "RELEASE-2026",
                        "packages": [
                            {
                                "type": "basic",
                                "url": f"https://data.neonscience.org/api/v0/data/package/{WIND}/ABBY/2023-03?package=basic",
                            }
                        ],
                        "files": files,
                        "externalData": [],
                    }
                }
            ),
            params={"package": "basic"},
            token=True,
        ),
        Route("GET", URLS[0], Reply(content=A, content_type="text/csv")),
        Route("GET", URLS[1], Reply(content=B, content_type="text/plain")),
    )


SELECT = {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-03"}


async def test_download_then_skip(token_server: NeonServer, router: FixtureRouter) -> None:
    listing_routes(router)
    report = await call_ok(token_server, "neon_download_files", SELECT)
    assert [f["status"] for f in report["files"]] == ["downloaded", "downloaded"]
    assert all(f["md5Verified"] for f in report["files"]) and report["totals"]["bytes"] == len(
        A
    ) + len(B)
    csv = Path(report["files"][0]["path"])
    assert csv.read_bytes() == A and csv.parent.parts[-3:] == (WIND, "ABBY", "2023-03")
    assert csv.is_relative_to(Path(report["downloadDir"]))
    storage = [c for c in router.calls if c.host == "storage.googleapis.com"]
    assert storage and not any(c.has_token for c in storage)
    assert report["nextSteps"][0].startswith("pandas.read_csv(")
    again = await call_ok(token_server, "neon_download_files", SELECT)
    assert [f["status"] for f in again["files"]] == ["skipped", "skipped"]
    await call_err(
        token_server, "neon_download_files", {**SELECT, "if_exists": "error"}, "download_denied"
    )


async def test_filters_subdir_and_checksum(token_server: NeonServer, router: FixtureRouter) -> None:
    listing_routes(router, bad_md5=True)
    report = await call_ok(
        token_server, "neon_download_files", {**SELECT, "dest_subdir": "proj/run1"}
    )
    statuses = {f["name"]: f["status"] for f in report["files"]}
    assert statuses == {NAMES[0]: "failed", NAMES[1]: "downloaded"}
    assert "proj/run1" in report["files"][1]["path"] and report["notes"]
    only = await call_ok(
        token_server, "neon_download_files", {**SELECT, "kind": "readme", "dest_subdir": "b"}
    )
    assert [f["name"] for f in only["files"]] == [NAMES[1]]
    await call_err(
        token_server,
        "neon_download_files",
        {**SELECT, "dest_subdir": "../escape"},
        "download_denied",
    )


async def test_plan_is_refused_before_transfer(
    token_server: NeonServer, router: FixtureRouter
) -> None:
    listing_routes(router)
    token_server.config.downloads.max_files_per_call = 1
    err = await call_err(token_server, "neon_download_files", SELECT, "download_limit_exceeded")
    assert err["details"]["files"] == 2
    assert not [c for c in router.calls if c.host == "storage.googleapis.com"]


async def test_zip_packages(token_server: NeonServer, router: FixtureRouter) -> None:
    listing_routes(router)
    router.add(
        Route(
            "GET",
            f"/data/package/{WIND}/ABBY/2023-03",
            Reply(content=b"PK\x03\x04zip", content_type="application/zip"),
            params={"package": "basic"},
            token=True,
        )
    )
    report = await call_ok(token_server, "neon_download_files", {**SELECT, "as_zip": True})
    assert report["files"][0]["name"] == f"NEON.{WIND}.ABBY.2023-03.basic.zip"
    assert (
        router.calls_to(f"GET /data/package/{WIND}/ABBY/2023-03")[0].headers["x-api-token"]
        == TEST_TOKEN
    )


async def test_prototype_and_document_need_no_token(
    server: NeonServer, router: FixtureRouter
) -> None:
    proto_url = "https://neon-publication-proto.storage.googleapis.com/datasets/x/small.csv"
    router.add(
        Route(
            "GET",
            f"/prototype/data/{PROTOTYPE_UUID}",
            Reply(
                json={
                    "data": {
                        "datasetUuid": PROTOTYPE_UUID,
                        "files": [
                            {
                                "name": "Small",
                                "fileName": "small.csv",
                                "size": len(A),
                                "md5": md5(A),
                                "url": proto_url,
                            }
                        ],
                        "dataLocations": [],
                    }
                }
            ),
        ),
        Route("GET", proto_url, Reply(content=A, content_type="text/csv")),
        Route(
            "GET",
            "/documents/NEON.DOC.000780vD",
            Reply(content=b"%PDF-1.4 tiny", content_type="application/pdf"),
        ),
    )
    proto = await call_ok(server, "neon_download_files", {"prototype_uuid": PROTOTYPE_UUID})
    assert proto["files"][0]["status"] == "downloaded" and "prototype" in proto["files"][0]["path"]
    assert f"neon_get_citation(prototype_uuid='{PROTOTYPE_UUID}')" in proto["nextSteps"]
    doc = await call_ok(server, "neon_download_files", {"spec_number": "NEON.DOC.000780vD"})
    assert doc["files"][0]["path"].endswith("documents/NEON.DOC.000780vD.pdf")
    await call_err(
        server,
        "neon_download_files",
        {"prototype_uuid": PROTOTYPE_UUID, "file_names": ["nope.csv"]},
        "not_found",
    )
    await call_err(server, "neon_download_files", SELECT, "auth_required")


async def test_selector_validation_and_modes(
    token_server: NeonServer, make_server: Callable[..., NeonServer]
) -> None:
    await call_err(token_server, "neon_download_files", {}, "invalid_argument")
    await call_err(
        token_server,
        "neon_download_files",
        {**SELECT, "prototype_uuid": PROTOTYPE_UUID},
        "invalid_argument",
    )
    await call_err(token_server, "neon_download_files", {"product": WIND}, "invalid_argument")
    http = make_server(transport="http", token=TEST_TOKEN)
    assert "neon_download_files" not in [t.name for t in http.tools]
    await call_err(http, "neon_download_files", SELECT, "not_available_in_http_mode")
    off = make_server(token=TEST_TOKEN)
    off.config.downloads.enabled = False
    assert "neon_download_files" not in [t.name for t in off.tools]
    await call_err(off, "neon_download_files", SELECT, "feature_unavailable")
