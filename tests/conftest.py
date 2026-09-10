"""Shared fixtures: hermetic NEON router, config, server factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from neon_mcp.config import Config
from neon_mcp.logging import forget_secrets
from neon_mcp.neon.auth import _reset_warning_for_tests
from neon_mcp.server import NeonServer, create_server
from tests.fixture_router import TEST_TOKEN, FixtureRouter


class FakeSleep:
    """Records requested sleeps instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    yield
    forget_secrets()
    _reset_warning_for_tests()


@pytest.fixture
def router() -> Iterator[FixtureRouter]:
    r = FixtureRouter()
    yield r
    assert not r.unexpected, f"unexpected upstream calls: {r.unexpected}"


@pytest.fixture
def fake_sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config.model_validate({"downloads": {"directory": str(tmp_path / "downloads")}})


@pytest.fixture
async def make_server(
    config: Config, router: FixtureRouter, fake_sleep: FakeSleep
) -> AsyncIterator[Callable[..., NeonServer]]:
    servers: list[NeonServer] = []

    def _make(
        *,
        transport: str = "stdio",
        token: str | None = None,
        config: Config | None = None,
        **_: Any,
    ) -> NeonServer:
        cfg = (config or _base).model_copy(deep=True)
        if token:
            cfg.neon.api_token = SecretStr(token)
        server = create_server(
            cfg, transport=transport, http_transport=router.transport, sleep=fake_sleep
        )  # type: ignore[arg-type]
        servers.append(server)
        return server

    _base = config
    yield _make
    for server in servers:
        await server.aclose()


@pytest.fixture
async def server(make_server: Callable[..., NeonServer]) -> NeonServer:
    return make_server()


@pytest.fixture
async def token_server(make_server: Callable[..., NeonServer]) -> NeonServer:
    return make_server(token=TEST_TOKEN)


@pytest.fixture
async def http_server(make_server: Callable[..., NeonServer], config: Config) -> NeonServer:
    """HTTP-mode server with prewarm off (tests opt in explicitly)."""
    cfg = config.model_copy(deep=True)
    cfg.cache.prewarm = False
    return make_server(transport="http", config=cfg)
