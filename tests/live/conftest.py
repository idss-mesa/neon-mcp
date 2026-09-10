"""Live tests against the real NEON API: opt in with NEON_MCP_LIVE=1 (token tests also need NEON_TOKEN)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from neon_mcp.config import load_config
from neon_mcp.server import NeonServer, create_server

LIVE = os.environ.get("NEON_MCP_LIVE") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "live" in item.nodeid.split("::")[0]:
            item.add_marker(pytest.mark.live)
            if not LIVE:
                item.add_marker(
                    pytest.mark.skip(reason="set NEON_MCP_LIVE=1 to run live NEON tests")
                )


@pytest.fixture
async def live(tmp_path: Path) -> AsyncIterator[NeonServer]:
    config = load_config()
    config.downloads.directory = tmp_path / "downloads"
    server = create_server(config, transport="stdio")
    yield server
    await server.aclose()


@pytest.fixture
def needs_token() -> None:
    if not load_config().token_value():
        pytest.skip("needs a NEON API token (NEON_MCP_NEON__API_TOKEN or NEON_TOKEN)")
