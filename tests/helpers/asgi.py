"""Drive the real Streamable HTTP app in-process (lifespan included)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from mcp.types import LATEST_PROTOCOL_VERSION

from neon_mcp.server import NeonServer
from neon_mcp.transport.streamable_http import app_lifecycle, build_http_app

BASE_URL = "http://127.0.0.1:8080"
REQUEST_META: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": LATEST_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}


class AppHarness:
    """Run the Starlette app with its lifespan and :func:`app_lifecycle` active.

    The SDK's session manager starts its task group in the lifespan, so a bare
    ``ASGITransport`` request would fail with "Task group is not initialized".
    """

    def __init__(self, server: NeonServer, app: Any = None, *, base_url: str = BASE_URL) -> None:
        self.server = server
        self.app = app if app is not None else build_http_app(server)
        self.base_url = base_url
        self._recv: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._send: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._lifecycle: Any = None
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._lifecycle = app_lifecycle(self.server)
        await self._lifecycle.__aenter__()
        await self._recv.put({"type": "lifespan.startup"})
        self._task = asyncio.create_task(
            self.app({"type": "lifespan"}, self._recv.get, self._send.put)
        )
        message = await self._send.get()
        assert message["type"] == "lifespan.startup.complete", message
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=self.base_url
        )
        return self.client

    async def __aexit__(self, *exc: Any) -> None:
        assert self.client is not None
        await self.client.aclose()
        await self._recv.put({"type": "lifespan.shutdown"})
        await self._send.get()
        if self._task is not None:
            self._task.cancel()
        await self._lifecycle.__aexit__(None, None, None)


def mcp_headers(method: str, name: str | None = None, **extra: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    headers.update(extra)
    return headers


def parse_rpc(response: httpx.Response) -> dict[str, Any]:
    """A JSON-RPC message from a JSON body or a single SSE frame."""
    for line in response.text.splitlines():
        if line.startswith("data:"):
            parsed: dict[str, Any] = json.loads(line[5:].strip())
            return parsed
    body: dict[str, Any] = response.json()
    return body


async def rpc(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    name: str | None = None,
    headers: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: int = 1,
) -> tuple[httpx.Response, dict[str, Any]]:
    """POST one 2026-07-28 JSON-RPC request to /mcp."""
    body_params = dict(params or {})
    body_params["_meta"] = {**REQUEST_META, **(meta or {})}
    if name is None and method in ("tools/call", "prompts/get"):
        name = body_params.get("name")
    if name is None and method == "resources/read":
        name = body_params.get("uri")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": body_params},
        headers={**mcp_headers(method, name), **(headers or {})},
    )
    try:
        parsed = parse_rpc(response)
    except ValueError:
        parsed = {}
    return response, parsed
