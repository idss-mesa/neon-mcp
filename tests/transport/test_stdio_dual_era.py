"""Run ``neon-mcp`` as a real stdio subprocess and speak both protocol eras to it."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "neon-mcp-tests", "version": "0"},
}


async def _exchange(
    messages: list[dict[str, Any]], tmp_path: Path
) -> tuple[list[dict[str, Any]], str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("NEON_MCP_", "NEON_TOKEN", "NEON_API_TOKEN"))
    }
    env["NEON_MCP_DOWNLOADS__DIRECTORY"] = str(tmp_path / "dl")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "neon_mcp",
        "--transport",
        "stdio",
        "--log-level",
        "info",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=4 * 1024 * 1024,  # one tools/list line exceeds asyncio's 64 KiB default
    )
    assert proc.stdin and proc.stdout and proc.stderr
    replies: list[dict[str, Any]] = []
    for message in messages:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()
        if "id" in message:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            replies.append(json.loads(line))
    proc.stdin.close()
    rest = await asyncio.wait_for(proc.stdout.read(), timeout=30)
    err = await asyncio.wait_for(proc.stderr.read(), timeout=30)
    await asyncio.wait_for(proc.wait(), timeout=30)
    return replies, rest.decode(), err.decode()


async def test_modern_era_over_stdio(tmp_path: Path) -> None:
    replies, rest, err = await _exchange(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "neon_ping", "arguments": {}, "_meta": META},
            },
        ],
        tmp_path,
    )
    assert [r["id"] for r in replies] == [1, 2]
    names = [t["name"] for t in replies[0]["result"]["tools"]]
    assert "neon_ping" in names and names == sorted(names)
    result = replies[1]["result"]
    assert result["structuredContent"]["pong"] == "ok"
    assert result["structuredContent"]["transport"] == "stdio"
    assert "io.neon-mcp/upstream" in result["_meta"]
    assert rest.strip() == ""  # nothing but framing on stdout
    assert "tool.call" in err  # logs go to stderr


async def test_legacy_era_over_stdio(tmp_path: Path) -> None:
    replies, rest, _ = await _exchange(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "legacy", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "neon_ping", "arguments": {}},
            },
        ],
        tmp_path,
    )
    assert replies[0]["result"]["serverInfo"]["name"] == "neon-mcp"
    assert "neon_ping" in [t["name"] for t in replies[1]["result"]["tools"]]
    assert replies[2]["result"]["structuredContent"]["pong"] == "ok"
    assert rest.strip() == ""
