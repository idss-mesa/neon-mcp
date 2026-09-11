from __future__ import annotations

import json

from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN, FixtureRouter, Reply, load_headers
from tests.helpers import call_ok


async def test_ping_makes_no_request(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_ping")
    assert router.calls == []
    assert payload["pong"] == "ok"
    assert payload["protocolVersion"] == "2026-07-28"
    assert payload["tokenConfigured"] is False and payload["tokenSource"] == "none"
    assert payload["downloadsEnabled"] is True and payload["downloadDir"]
    assert any("token" in note for note in payload["notes"])
    assert payload["nextSteps"]
    assert payload["catalog"]["products"] == "cold"


async def test_ping_with_token_never_reveals_it(token_server: NeonServer) -> None:
    payload = await call_ok(token_server, "neon_ping")
    assert payload["tokenConfigured"] is True and payload["tokenSource"] == "config"
    assert TEST_TOKEN not in json.dumps(payload)
    assert TEST_TOKEN[:8] not in json.dumps(payload)


async def test_ping_check_api_reads_rate_limits(
    token_server: NeonServer, router: FixtureRouter
) -> None:
    payload = await call_ok(token_server, "neon_ping", {"check_api": True})
    assert router.paths() == ["GET /taxonomy"]
    assert router.calls[0].params == {"taxonTypeCode": "TICK", "limit": "1"}
    assert router.calls[0].has_token  # stdio sends the token to public endpoints by default
    assert payload["api"]["reachable"] is True and payload["api"]["status"] == 200
    assert payload["rateLimit"]["limit"] == 200 and payload["rateLimit"]["identity"] == "token"
    assert payload["source"]["endpoints"] == ["GET /taxonomy"]


async def test_ping_check_api_reports_failure(server: NeonServer, router: FixtureRouter) -> None:
    router.inject_5xx(3)
    payload = await call_ok(server, "neon_ping", {"check_api": True})
    assert payload["api"]["status"] == 502
    assert len(router.calls) == 3


async def test_ping_reports_a_rejected_token(
    token_server: NeonServer, router: FixtureRouter
) -> None:
    # NEON answers 403 "Access Denied" to an invalid token even on public endpoints.
    router.inject(
        Reply(fixture="data_403.json", status=403, headers=load_headers("example_403.headers"))
    )
    payload = await call_ok(token_server, "neon_ping", {"check_api": True})
    assert payload["api"]["status"] == 403 and len(router.calls) == 1
    assert any("rejected the API token" in note for note in payload["notes"])
    assert any("NEON_TOKEN" in step for step in payload["nextSteps"])
    assert TEST_TOKEN not in json.dumps(payload)


async def test_ping_over_http_has_no_downloads(http_server: NeonServer) -> None:
    payload = await call_ok(http_server, "neon_ping")
    assert payload["transport"] == "http"
    assert payload["downloadsEnabled"] is False
    assert "downloadDir" not in payload
