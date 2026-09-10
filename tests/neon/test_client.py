from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from neon_mcp.config import CacheConfig, NeonConfig
from neon_mcp.context import UpstreamStats
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.neon.auth import Token
from neon_mcp.neon.cache import TTLCache
from neon_mcp.neon.client import NeonClient, host_allowed
from neon_mcp.neon.gql_queries import SITES_FOR_RELEASE
from neon_mcp.neon.ratelimit import RateLimiter
from tests.conftest import FakeSleep
from tests.fixture_router import TEST_TOKEN, FixtureRouter, Reply, Route

TOKEN = Token(TEST_TOKEN, "config")
BLOB = bytes(range(256)) * 256  # 64 KiB
BLOB_URL = "https://storage.googleapis.com/fixture/download_small.bin"


def make_client(
    router: FixtureRouter | httpx.AsyncBaseTransport,
    sleep: FakeSleep,
    *,
    send_token_on_public: bool = False,
) -> NeonClient:
    cfg = NeonConfig()
    transport = router.transport if isinstance(router, FixtureRouter) else router
    return NeonClient(
        cfg,
        cache=TTLCache(CacheConfig()),
        limiter=RateLimiter(cfg.rate_limit, max_concurrency=4, sleep=sleep),
        send_token_on_public=send_token_on_public,
        transport=transport,
        sleep=sleep,
    )


@pytest.fixture
async def client(router: FixtureRouter, fake_sleep: FakeSleep) -> NeonClient:
    c = make_client(router, fake_sleep)
    yield c  # type: ignore[misc]
    await c.aclose()


async def test_get_json_unwraps_and_records(client: NeonClient, router: FixtureRouter) -> None:
    stats = UpstreamStats()
    env = await client.get_json("/sites", token=None, stats=stats)
    assert [s["siteCode"] for s in env.data] == ["ABBY", "HARV", "SRER"]
    assert env.status == 200 and env.endpoint == "GET /sites" and env.cache == "bypass"
    assert (
        stats.requests == 1 and stats.rate_limit_limit == 200 and stats.endpoints == ["GET /sites"]
    )


async def test_cache_hit_avoids_second_request(client: NeonClient, router: FixtureRouter) -> None:
    stats = UpstreamStats()
    await client.get_json("/releases", token=None, cache="catalog", stats=stats)
    env = await client.get_json("/releases", token=None, cache="catalog", stats=stats)
    assert env.cache == "hit" and len(router.calls) == 1 and stats.cache_hits == 1


async def test_errors_raise_with_detail_and_data(client: NeonClient) -> None:
    with pytest.raises(NeonApiError) as exc:
        await client.get_json("/products/DP9.99999.999", token=None)
    assert exc.value.status == 400 and exc.value.detail == "Product code not found"
    with pytest.raises(NeonApiError) as exc2:
        await client.get_json("/products/DP1.00001.001", {"release": "RELEASE-1999"}, token=None)
    assert exc2.value.data["validReleases"][-1] == "RELEASE-2026"


async def test_token_placement(router: FixtureRouter, fake_sleep: FakeSleep) -> None:
    quiet = make_client(router, fake_sleep, send_token_on_public=False)
    loud = make_client(router, fake_sleep, send_token_on_public=True)
    await quiet.get_json("/sites", token=TOKEN)
    await quiet.get_json("/data/DP1.00001.001/ABBY/2023-01", {"package": "basic"}, token=TOKEN)
    await loud.get_json("/releases", token=TOKEN)
    assert [c.has_token for c in router.calls] == [False, True, True]
    assert router.calls[1].headers["x-api-token"] == TEST_TOKEN
    await quiet.aclose()
    await loud.aclose()


async def test_missing_token_gets_neon_403(client: NeonClient) -> None:
    with pytest.raises(NeonApiError) as exc:
        await client.get_json("/data/DP1.00001.001/ABBY/2023-01", {"package": "basic"}, token=None)
    assert (
        exc.value.status == 403
        and exc.value.token_sent is False
        and exc.value.detail == "Access Denied"
    )


async def test_429_retries_after_retryafter(
    client: NeonClient, router: FixtureRouter, fake_sleep: FakeSleep
) -> None:
    router.inject_429(1)
    env = await client.get_json("/sites", token=None)
    assert env.status == 200 and len(router.calls) == 2
    assert 1.0 in fake_sleep.calls


async def test_429_exhausted(client: NeonClient, router: FixtureRouter) -> None:
    router.inject_429(3)
    with pytest.raises(NeonApiError) as exc:
        await client.get_json("/sites", token=None)
    assert exc.value.status == 429 and exc.value.retry_after_s == 1.0


async def test_5xx_backoff_then_success(
    client: NeonClient, router: FixtureRouter, fake_sleep: FakeSleep
) -> None:
    router.inject_5xx(2)
    env = await client.get_json("/sites", token=None)
    assert env.status == 200
    assert 0.5 <= fake_sleep.calls[0] <= 0.75 and 1.0 <= fake_sleep.calls[1] <= 1.25


async def test_5xx_exhausted_raises(client: NeonClient, router: FixtureRouter) -> None:
    router.inject_5xx(3)
    with pytest.raises(NeonApiError) as exc:
        await client.get_json("/sites", token=None)
    assert exc.value.status == 502 and "upstream failed" in exc.value.detail


async def test_transport_errors_become_transport_kind(fake_sleep: FakeSleep) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("refused", request=request)

    c = make_client(httpx.MockTransport(handler), fake_sleep)
    with pytest.raises(NeonApiError) as exc:
        await c.get_json("/sites", token=None)
    assert exc.value.kind == "transport" and exc.value.status == 0 and len(attempts) == 3
    await c.aclose()


async def test_non_json_success_is_decode_error(client: NeonClient, router: FixtureRouter) -> None:
    router.add(Route("GET", "/weird", Reply(content=b"<html>hi</html>", content_type="text/html")))
    with pytest.raises(NeonApiError) as exc:
        await client.get_json("/weird", token=None)
    assert exc.value.kind == "decode" and exc.value.content_type == "text/html"


async def test_post_json_and_body_cache(client: NeonClient, router: FixtureRouter) -> None:
    body = {
        "productCode": "DP1.00001.001",
        "siteCodes": ["ABBY"],
        "startDateMonth": "2023-01",
        "endDateMonth": "2023-02",
        "package": "basic",
        "includeProvisional": True,
    }
    env = await client.post_json("/data/query", body, token=TOKEN, cache="data")
    again = await client.post_json(
        "/data/query", dict(reversed(body.items())), token=TOKEN, cache="data"
    )
    assert env.data["productCode"] == "DP1.00001.001" and again.cache == "hit"
    assert len(router.calls) == 1 and router.calls[0].body == body


async def test_graphql_payloads(client: NeonClient, router: FixtureRouter) -> None:
    env = await client.graphql(SITES_FOR_RELEASE, {"release": "RELEASE-2026"}, token=TOKEN)
    assert env.data["errors"] is None and len(env.data["data"]["sites"]) == 5
    assert router.calls[-1].operation == "NeonMcpSitesForRelease"
    assert not router.calls[-1].has_token  # public endpoint, send_token_on_public=False
    user = await client.graphql("{ nope }", token=None)
    assert (
        user.data["data"] is None
        and user.data["errors"][0]["extensions"]["classification"] == "ValidationError"
    )


async def test_head_and_ranged_fallback(client: NeonClient, router: FixtureRouter) -> None:
    router.add(
        Route(
            "HEAD",
            "/documents/NEON.DOC.000780vD",
            Reply(
                content=b"",
                content_type="application/pdf",
                headers={
                    "content-length": "715529",
                    "content-disposition": 'attachment; filename="NEON.DOC.000780vD.pdf"',
                },
            ),
        ),
        Route("HEAD", "/documents/NEON.DOC.999999vA", Reply(status=405)),
        Route(
            "GET",
            "/documents/NEON.DOC.999999vA",
            Reply(
                content=b"%",
                status=206,
                content_type="application/pdf",
                headers={"content-range": "bytes 0-0/1234"},
            ),
        ),
    )
    info = await client.head("/documents/NEON.DOC.000780vD", token=None)
    assert (info.content_type, info.content_length, info.filename) == (
        "application/pdf",
        715529,
        "NEON.DOC.000780vD.pdf",
    )
    ranged = await client.head("/documents/NEON.DOC.999999vA", token=None)
    assert ranged.content_length == 1234 and router.calls[-1].headers["range"] == "bytes=0-0"


async def test_resolve_redirect(client: NeonClient, router: FixtureRouter) -> None:
    path = (
        "/data/DP1.00001.001/ABBY/2023-01/NEON.D16.ABBY.DP1.00001.001.readme.20250128T000000Z.txt"
    )
    router.add(
        Route(
            "GET",
            path,
            Reply(status=302, headers={"location": BLOB_URL + "?X-Goog-Signature=REDACTED"}),
            token=True,
        )
    )
    assert (
        await client.resolve_redirect(path, token=TOKEN) == BLOB_URL + "?X-Goog-Signature=REDACTED"
    )
    router.add(
        Route(
            "GET",
            "/data/DP1.00001.001/ABBY/2023-01/plain.txt",
            Reply(json={"data": {}}),
            token=True,
        )
    )
    assert (
        await client.resolve_redirect("/data/DP1.00001.001/ABBY/2023-01/plain.txt", token=TOKEN)
        is None
    )


def _blob_route(router: FixtureRouter) -> None:
    router.add(Route("GET", BLOB_URL, Reply(content=BLOB, content_type="application/octet-stream")))


async def test_fetch_bytes_limits_and_hosts(client: NeonClient, router: FixtureRouter) -> None:
    _blob_route(router)
    assert await client.fetch_bytes(BLOB_URL, token=TOKEN, max_bytes=len(BLOB)) == BLOB
    assert not router.calls[-1].has_token  # never to storage hosts
    with pytest.raises(ToolError) as exc:
        await client.fetch_bytes(BLOB_URL, token=None, max_bytes=100)
    assert exc.value.code == "result_too_large"
    with pytest.raises(ToolError) as denied:
        await client.fetch_bytes("https://evil.example/x", token=None, max_bytes=100)
    assert denied.value.code == "download_denied"


async def test_redirect_to_disallowed_host_is_refused(
    client: NeonClient, router: FixtureRouter
) -> None:
    router.add(
        Route(
            "GET",
            "/documents/NEON.DOC.000001vA",
            Reply(status=302, headers={"location": "https://evil.example/a"}),
        )
    )
    with pytest.raises(ToolError) as exc:
        await client.fetch_bytes("/documents/NEON.DOC.000001vA", token=None, max_bytes=10)
    assert exc.value.code == "download_denied"


async def test_stream_to_file(client: NeonClient, router: FixtureRouter, tmp_path: Path) -> None:
    _blob_route(router)
    md5 = hashlib.md5(BLOB).hexdigest()  # noqa: S324
    out = await client.stream_to_file(
        BLOB_URL, tmp_path / "a" / "blob.bin", token=TOKEN, max_bytes=10**6, expected_md5=md5
    )
    assert (
        out.md5_verified is True
        and out.bytes == len(BLOB)
        and (tmp_path / "a" / "blob.bin").read_bytes() == BLOB
    )
    with pytest.raises(ToolError) as bad:
        await client.stream_to_file(
            BLOB_URL, tmp_path / "b.bin", token=None, max_bytes=10**6, expected_md5="0" * 32
        )
    assert bad.value.code == "checksum_mismatch"
    assert not (tmp_path / "b.bin").exists() and not (tmp_path / "b.bin.part").exists()
    with pytest.raises(ToolError) as big:
        await client.stream_to_file(
            BLOB_URL, tmp_path / "c.bin", token=None, max_bytes=1000, expected_md5=None
        )
    assert big.value.code == "download_limit_exceeded" and not list(tmp_path.glob("c.bin*"))
    unverified = await client.stream_to_file(
        BLOB_URL, tmp_path / "d.bin", token=None, max_bytes=10**6, expected_md5=None
    )
    assert unverified.md5_verified is None


def test_host_allowlist() -> None:
    allowed = ["data.neonscience.org", "storage.googleapis.com", "*.storage.googleapis.com"]
    assert host_allowed("https://storage.googleapis.com/x", allowed)
    assert host_allowed("https://neon-publication-proto.storage.googleapis.com/x", allowed)
    assert not host_allowed("http://storage.googleapis.com/x", allowed)
    assert not host_allowed("https://storage.googleapis.com.evil.example/x", allowed)
    assert not host_allowed("https://evilstorage.googleapis.com/x", allowed)


async def test_snapshot_and_stats(client: NeonClient) -> None:
    await client.get_json("/sites", token=None)
    snap = client.rate_limit_snapshot("anon")
    assert snap is not None and snap.limit == 200
    assert client.cache_stats().entries == 0
