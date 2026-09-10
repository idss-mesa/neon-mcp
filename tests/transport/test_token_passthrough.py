"""Per-request NEON tokens over HTTP: the TLS gate, sharing policy and redaction."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from pydantic import SecretStr

from neon_mcp.config import Config
from neon_mcp.logging import setup_logging
from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN, FixtureRouter
from tests.helpers.asgi import AppHarness, rpc

HOST = "neon.example.test"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield
    setup_logging("warning", "stdio")


def _server(
    make_server: Callable[..., NeonServer],
    config: Config,
    *,
    token: str | None = None,
    **server: Any,
) -> NeonServer:
    cfg = config.model_copy(deep=True)
    cfg.cache.prewarm = False
    if token:
        cfg.neon.api_token = SecretStr(token)
    for key, value in server.items():
        setattr(cfg.server, key, value)
    return make_server(transport="http", config=cfg)


async def _ping(
    server: NeonServer,
    *,
    headers: dict[str, str] | None = None,
    base_url: str | None = None,
    check_api: bool = False,
) -> tuple[str, dict[str, Any]]:
    harness = AppHarness(server, base_url=base_url) if base_url else AppHarness(server)
    async with harness as client:
        response, message = await rpc(
            client,
            "tools/call",
            {"name": "neon_ping", "arguments": {"check_api": check_api}},
            headers=headers,
        )
    return response.text, message["result"]["structuredContent"]


async def test_header_token_honoured_behind_tls(
    make_server: Callable[..., NeonServer], config: Config, router: FixtureRouter
) -> None:
    server = _server(make_server, config, public_base_url=f"https://{HOST}")
    text, payload = await _ping(
        server, headers={"X-API-Token": TEST_TOKEN}, base_url=f"http://{HOST}", check_api=True
    )
    assert payload["tokenConfigured"] is True and payload["tokenSource"] == "request"
    assert TEST_TOKEN not in text
    assert router.calls and not router.calls[0].has_token  # public probe: no token over http mode


async def test_header_token_ignored_without_tls(
    make_server: Callable[..., NeonServer], config: Config
) -> None:
    server = _server(make_server, config)
    _, payload = await _ping(server, headers={"X-API-Token": TEST_TOKEN})
    assert payload["tokenSource"] == "none"


async def test_insecure_override(make_server: Callable[..., NeonServer], config: Config) -> None:
    server = _server(make_server, config, allow_insecure_header_token=True)
    _, payload = await _ping(server, headers={"x-api-token": TEST_TOKEN})
    assert payload["tokenSource"] == "request"


async def test_config_token_not_shared_unless_opted_in(
    make_server: Callable[..., NeonServer], config: Config
) -> None:
    private = _server(make_server, config, token="operator-token-1234")
    _, payload = await _ping(private)
    assert payload["tokenSource"] == "none"
    shared = _server(
        make_server, config, token="operator-token-1234", share_config_token_over_http=True
    )
    _, payload = await _ping(shared)
    assert payload["tokenSource"] == "config"


async def test_token_never_logged(
    make_server: Callable[..., NeonServer], config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_logging("debug", "http")
    server = _server(make_server, config, public_base_url=f"https://{HOST}")
    await _ping(
        server, headers={"X-API-Token": TEST_TOKEN}, base_url=f"http://{HOST}", check_api=True
    )
    captured = capsys.readouterr()
    assert "tool.call" in captured.err
    assert TEST_TOKEN not in captured.err and TEST_TOKEN not in captured.out
