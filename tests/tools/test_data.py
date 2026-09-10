from __future__ import annotations

from neon_mcp.projections.common import parse_gcs_expiry
from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN, FixtureRouter, Reply, Route, load_fixture
from tests.helpers import call_err, call_ok

WIND = "DP1.00001.001"
README = "NEON.D16.ABBY.DP1.00001.001.readme.20250128T000000Z.txt"


async def test_token_required_before_any_request(server: NeonServer, router: FixtureRouter) -> None:
    err = await call_err(
        server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-01"},
        "auth_required",
    )
    assert err["details"]["guide"] == "neon://guide/api-token"
    assert router.calls == []


async def test_single_cell_listing(token_server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["abby"], "start_month": "2023-01"},
    )
    call = router.calls_to(f"GET /data/{WIND}/ABBY/2023-01")[0]
    assert call.params == {"package": "basic"} and call.headers["x-api-token"] == TEST_TOKEN
    files = payload["files"]
    assert [f["kind"] for f in files] == ["data", "readme", "variables"]
    assert (
        files[0]["table"] == "2DWSD_30min" and files[0]["hor"] == "000" and files[0]["tmi"] == "030"
    )
    assert files[0]["release"] == "RELEASE-2025" and files[0]["size"] == 112233
    assert payload["summary"]["fileCount"] == 3 and payload["summary"]["totalBytes"] == 117690
    assert (
        payload["summary"]["siteMonthsRequested"] == 1
        and payload["summary"]["siteMonthsWithData"] == 1
    )
    assert [p["type"] for p in payload["packages"]] == ["basic", "expanded"]
    assert payload["packages"][0]["requiresTokenHeader"] is True
    assert "$NEON_TOKEN" in payload["curlHint"] and TEST_TOKEN not in str(payload)
    raw_url = load_fixture("data_DP1.00001.001_ABBY_2023-01.json")["data"]["files"][0]["url"]
    assert payload.get("urlExpiresAt") == parse_gcs_expiry(raw_url)
    assert payload["nextSteps"][0].startswith("neon_download_files(")


async def test_filters_and_detail_modes(token_server: NeonServer) -> None:
    base = {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-01"}
    assert [
        f["kind"]
        for f in (await call_ok(token_server, "neon_list_files", {**base, "kind": "readme"}))[
            "files"
        ]
    ] == ["readme"]
    by_table = await call_ok(
        token_server,
        "neon_list_files",
        {**base, "table": "2dwsd_30MIN", "hor": "000", "tmi": "030"},
    )
    assert len(by_table["files"]) == 1
    named = await call_ok(token_server, "neon_list_files", {**base, "name_contains": "VARIABLES"})
    assert named["files"][0]["kind"] == "variables"
    no_urls = await call_ok(token_server, "neon_list_files", {**base, "include_urls": False})
    assert all("url" not in f for f in no_urls["files"])
    summary = await call_ok(token_server, "neon_list_files", {**base, "detail": "summary"})
    assert "files" not in summary and summary["summary"]["fileCount"] == 3
    rows = await call_ok(token_server, "neon_list_files", {**base, "detail": "site_months"})
    assert rows["siteMonths"][0]["fileCount"] == 3 and "files" not in rows
    paged = await call_ok(token_server, "neon_list_files", {**base, "limit": 1})
    assert paged["page"]["nextOffset"] == 1


async def test_query_mode_and_provisional(token_server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(
        token_server,
        "neon_list_files",
        {
            "product": WIND,
            "site_codes": ["ABBY", "HARV"],
            "startDateMonth": "2023-01",
            "end_month": "2023-02",
        },
    )
    body = router.calls_to("POST /data/query")[0].body
    assert body == {
        "productCode": WIND,
        "siteCodes": ["ABBY", "HARV"],
        "startDateMonth": "2023-01",
        "endDateMonth": "2023-02",
        "package": "basic",
        "includeProvisional": True,
    }
    summary = payload["summary"]
    assert summary["siteMonthsRequested"] == 4 and summary["siteMonthsWithData"] == 4
    assert summary["provisionalSiteMonths"] == 1
    assert [r["release"] for r in summary["releases"]] == ["RELEASE-2025", "PROVISIONAL"]
    assert (
        payload["files"][0]["release"] == "RELEASE-2025"
        and payload["files"][-1]["release"] == "PROVISIONAL"
    )
    assert any("PROVISIONAL" in n for n in payload["notes"])
    one_site = await call_ok(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-01", "end_month": "2023-02"},
    )
    assert one_site["summary"]["siteMonthsWithData"] == 2


async def test_filename_redirect(token_server: NeonServer, router: FixtureRouter) -> None:
    signed = "https://storage.googleapis.com/neon-publication/x/readme.txt?X-Goog-Date=20260910T000000Z&X-Goog-Expires=604800&X-Goog-Signature=REDACTED"
    router.add(
        Route(
            "GET",
            f"/data/{WIND}/ABBY/2023-01/{README}",
            Reply(status=302, headers={"location": signed}),
            token=True,
        )
    )
    payload = await call_ok(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-01", "filename": README},
    )
    assert [f["name"] for f in payload["files"]] == [README] and payload["files"][0][
        "url"
    ] == signed
    assert payload["urlExpiresAt"] == "2026-09-17T00:00:00Z"
    await call_err(
        token_server,
        "neon_list_files",
        {
            "product": WIND,
            "site_codes": ["ABBY", "HARV"],
            "start_month": "2023-01",
            "end_month": "2023-02",
            "filename": README,
        },
        "invalid_argument",
    )


async def test_guards(token_server: NeonServer, router: FixtureRouter) -> None:
    sites = [f"A{chr(65 + i // 26)}{chr(65 + i % 26)}Z" for i in range(25)]
    err = await call_err(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": sites, "start_month": "2021-01", "end_month": "2022-12"},
        "query_too_large",
    )
    assert err["details"]["siteMonths"] == 600
    await call_err(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": sites + sites[:6], "start_month": "2021-01"},
        "invalid_argument",
    )
    await call_err(
        token_server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-05", "end_month": "2023-01"},
        "invalid_argument",
    )
    assert router.calls == []


async def test_http_listing_points_to_urls(make_server) -> None:  # type: ignore[no-untyped-def]
    server = make_server(transport="http", token=TEST_TOKEN)
    server.config.server.share_config_token_over_http = True
    payload = await call_ok(
        server,
        "neon_list_files",
        {"product": WIND, "site_codes": ["ABBY"], "start_month": "2023-01"},
    )
    assert payload["nextSteps"][0].startswith("Downloads are stdio-only")
