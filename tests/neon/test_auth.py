from __future__ import annotations

import pytest

from neon_mcp.config import Config
from neon_mcp.errors import ToolError
from neon_mcp.neon.auth import (
    Token,
    header_token_allowed,
    is_token_endpoint,
    require_token,
    resolve_token,
)
from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN


def test_token_repr_is_redacted() -> None:
    token = Token(TEST_TOKEN, "config")
    assert TEST_TOKEN not in repr(token) and TEST_TOKEN not in str(token)
    assert "redacted" in repr(token)


def test_identity_is_stable_and_opaque() -> None:
    a, b = Token("abcdefgh1234", "config"), Token("abcdefgh1234", "request")
    assert a.identity() == b.identity()
    assert a.identity().startswith("tok:") and len(a.identity()) == 16
    assert "abcdefgh" not in a.identity()
    assert Token("other-token-99", "config").identity() != a.identity()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/data/DP1.00001.001/ABBY/2023-01", True),
        ("/data/query", True),
        ("/data/package/DP1.00001.001/ABBY/2023-01", True),
        ("/samples/view", True),
        ("/samples/download", True),
        ("/releases/RELEASE-2025/data/DP1.00001.001/ABBY/2023-01", True),
        ("/releases/RELEASE-2025", False),
        ("/releases/RELEASE-2025/products/DP1.00001.001", False),
        ("/products", False),
        ("/samples/classes", False),
        ("/taxonomy", False),
        ("/locations/HARV", False),
    ],
)
def test_token_endpoint_matrix(path: str, expected: bool) -> None:
    assert is_token_endpoint(path) is expected


def _cfg(**server: object) -> Config:
    return Config.model_validate({"neon": {"api_token": "config-token-1234"}, "server": server})


def test_stdio_uses_config_token_and_ignores_headers() -> None:
    token = resolve_token(
        _cfg(), transport="stdio", request_headers={"X-API-Token": "hdr-token-1234"}
    )
    assert token is not None and token.value == "config-token-1234" and token.source == "config"
    assert resolve_token(Config(), transport="stdio", request_headers=None) is None


@pytest.mark.parametrize(
    ("server", "headers", "expected"),
    [
        (
            {"public_base_url": "https://neon.example"},
            {"x-api-token": "hdr-token-1234"},
            ("hdr-token-1234", "request"),
        ),
        ({"public_base_url": "http://neon.example"}, {"x-api-token": "hdr-token-1234"}, None),
        ({}, {"x-api-token": "hdr-token-1234"}, None),
        (
            {"allow_insecure_header_token": True},
            {"X-Api-Token": "hdr-token-1234"},
            ("hdr-token-1234", "request"),
        ),
        (
            {"public_base_url": "https://n", "accept_header_token": False},
            {"x-api-token": "hdr-token-1234"},
            None,
        ),
        ({"share_config_token_over_http": True}, {}, ("config-token-1234", "config")),
        (
            {"share_config_token_over_http": True, "public_base_url": "https://n"},
            {"x-api-token": "hdr-token-1234"},
            ("hdr-token-1234", "request"),
        ),
        (
            {"public_base_url": "https://n", "request_token_header": "X-NEON-Token"},
            {"x-neon-token": "hdr-token-1234"},
            ("hdr-token-1234", "request"),
        ),
        ({"public_base_url": "https://n"}, {"x-api-token": "   "}, None),
    ],
)
def test_http_resolution_matrix(
    server: dict[str, object], headers: dict[str, str], expected: tuple[str, str] | None
) -> None:
    token = resolve_token(_cfg(**server), transport="http", request_headers=headers)
    if expected is None:
        assert token is None
    else:
        assert token is not None and (token.value, token.source) == expected


def test_header_token_gate() -> None:
    assert header_token_allowed(_cfg(public_base_url="https://x"))
    assert not header_token_allowed(_cfg(public_base_url="http://x"))
    assert header_token_allowed(_cfg(allow_insecure_header_token=True))


def test_require_token(server: NeonServer, token_server: NeonServer) -> None:
    with pytest.raises(ToolError) as exc:
        require_token(server.tool_context("t"), endpoint="GET /data/query")
    assert exc.value.code == "auth_required"
    assert require_token(token_server.tool_context("t"), endpoint="x").value == TEST_TOKEN
