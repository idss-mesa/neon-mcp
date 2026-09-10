---
title: "Transports"
description: "The stdio and stateless Streamable HTTP transports: endpoints, health checks, DNS-rebinding protection and per-request NEON tokens."
type: Reference
tags:
  - mcp
  - transports
  - http
  - stdio
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: mcp-transports
    resource: "https://modelcontextprotocol.io/specification/2026-07-28/basic/transports"
    title: "MCP specification — Transports"
    author: "team:modelcontextprotocol"
status: stable
---

# Transports

## stdio (default)

`neon-mcp` (or `neon-mcp --transport stdio`) serves one client over standard input
and output — the usual setup for Claude Code, Claude Desktop, Codex CLI, OpenCode and
Antigravity. Only MCP framing goes to stdout; logs go to stderr. The configured token
is used for every NEON request, and `neon_download_files` is available.

## Streamable HTTP (stateless)

`neon-mcp --transport http` serves[^mcp-transports]:

| Route | Behaviour |
| --- | --- |
| `POST /mcp` (and `/mcp/`) | JSON-RPC over Streamable HTTP; one response per request (a single SSE frame, or JSON with `server.json_response`) |
| `GET /mcp`, `DELETE /mcp` | 405 — the server sends no server-initiated messages and keeps no sessions |
| `GET /healthz` | liveness: `{"status": "ok", "version", "protocolVersion", "transport"}` |
| `GET /readyz` | 503 `{"status": "warming"}` while the catalogs prewarm, then 200 with catalog warmth, `degraded` and `tokenConfigured` |

Every response carries `X-Request-Id` (yours, if you sent a well-formed one). Request
bodies are capped at 1 MiB.

### Host and origin checks

DNS-rebinding protection is on automatically for loopback binds. For a public
deployment set `server.public_base_url` (its host and origin join the allow-lists)
and optionally `server.allowed_hosts` / `server.allowed_origins`; a request with any
other `Host` gets 421. Behind a proxy that rewrites `Host`, set
`server.dns_rebinding_protection = false`.

### Per-request NEON tokens

Callers send their own NEON token in `X-API-Token` (configurable with
`server.request_token_header`). It is honoured only when `server.public_base_url`
starts with `https://` — i.e. TLS terminates in front of the server — or when
`server.allow_insecure_header_token` is set for development; otherwise the header is
stripped and one warning is logged. Over HTTP the token is sent only to NEON's
token-only endpoints, and the operator's configured token is not used for anonymous
callers unless `server.share_config_token_over_http` is set.

[^mcp-transports]: MCP specification — Transports. <https://modelcontextprotocol.io/specification/2026-07-28/basic/transports>
