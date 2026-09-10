from __future__ import annotations

import asyncio
from collections.abc import Callable

from neon_mcp.config import Config
from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN, FixtureRouter
from tests.helpers.asgi import AppHarness


async def test_healthz_is_public_and_secret_free(
    make_server: Callable[..., NeonServer], config: Config
) -> None:
    cfg = config.model_copy(deep=True)
    cfg.cache.prewarm = False
    server = make_server(transport="http", config=cfg, token=TEST_TOKEN)
    async with AppHarness(server) as client:
        response = await client.get("/healthz")
        ready = await client.get("/readyz")
    body = response.json()
    assert response.status_code == 200
    assert (
        body["status"] == "ok"
        and body["protocolVersion"] == "2026-07-28"
        and body["transport"] == "http"
    )
    assert TEST_TOKEN not in response.text and TEST_TOKEN not in ready.text
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "catalog": {"products": "cold", "sites": "cold"},
        "degraded": False,
        "tokenConfigured": True,
    }


async def test_readyz_warming_then_ready(
    make_server: Callable[..., NeonServer], router: FixtureRouter
) -> None:
    server = make_server(transport="http")  # prewarm defaults on for http
    async with AppHarness(server) as client:
        server.readiness = "warming"
        warming = await client.get("/readyz")
        for _ in range(200):
            if server.catalog.warmth().sites == "warm":
                break
            await asyncio.sleep(0.01)
        server.readiness = "ready"
        ready = await client.get("/readyz")
    assert warming.status_code == 503 and warming.json() == {"status": "warming"}
    assert ready.status_code == 200 and ready.json()["catalog"] == {
        "products": "warm",
        "sites": "warm",
    }
    assert {"POST graphql:NeonMcpProductsCatalog", "POST graphql:NeonMcpSitesCatalog"} <= set(
        router.paths()
    )


async def test_readyz_degraded_after_failed_prewarm(
    make_server: Callable[..., NeonServer], router: FixtureRouter
) -> None:
    router.inject_5xx(40)
    server = make_server(transport="http")
    async with AppHarness(server) as client:
        for _ in range(300):
            if server.readiness == "degraded":
                break
            await asyncio.sleep(0.01)
        response = await client.get("/readyz")
    assert response.status_code == 200 and response.json()["degraded"] is True
