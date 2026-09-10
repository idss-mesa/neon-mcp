"""stdio transport: one user, logs on stderr, MCP framing alone on stdout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.stdio import stdio_server

from neon_mcp.context import current_transport

if TYPE_CHECKING:
    from neon_mcp.server import NeonServer


async def serve_stdio(server: NeonServer) -> None:
    """Serve until stdin closes. The SDK loop is dual-era (legacy handshake or 2026-07-28)."""
    current_transport.set("stdio")
    mcp_server = server.build_mcp_server()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream, write_stream, mcp_server.create_initialization_options()
            )
    finally:
        await server.aclose()
