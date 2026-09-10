---
title: "Clients"
description: "Register neon-mcp with Claude Code, Claude Desktop, Codex CLI, OpenCode and Antigravity over stdio, or connect to a hosted server over HTTP."
type: Guide
tags:
  - getting-started
  - clients
  - claude-code
  - codex
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: claude-code-mcp
    resource: "https://docs.claude.com/en/docs/claude-code/mcp"
    title: "Claude Code — MCP"
    author: "team:anthropic"
  - id: codex-mcp
    resource: "https://developers.openai.com/codex/cli/"
    title: "OpenAI Codex CLI"
    author: "team:openai"
  - id: opencode-mcp
    resource: "https://opencode.ai/docs/mcp-servers/"
    title: "OpenCode — MCP servers"
    author: "team:opencode"
  - id: mesa-install
    resource: "https://github.com/idss-mesa/docs/blob/main/install.sh"
    title: "idss-mesa installer (client registration conventions)"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# Clients

Local clients start neon-mcp themselves over **stdio**; hosted deployments are reached
over **Streamable HTTP**. The examples use `neon-mcp` on your `PATH` (see
[Install](install.md)); replace it with an absolute path such as
`/home/me/neon-mcp/.venv/bin/neon-mcp` when the client does not share your shell's
`PATH`. JSON-configured clients do not expand `~` or `$HOME`, so use absolute paths
there[^mesa-install].

The token is optional; see [NEON API token](api-token.md). Put it in the client's
environment settings, never in a shared or committed file.

## Claude Code

```bash
claude mcp add neon -s user -e NEON_TOKEN="$NEON_TOKEN" -- neon-mcp --transport stdio
claude mcp list
```

`-s user` makes the server available in every project[^claude-code-mcp]; drop the `-e`
option to run without a token.

## Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`;
Windows: `%APPDATA%\Claude\`) and restart the app:

```json
{
  "mcpServers": {
    "neon": {
      "command": "/absolute/path/to/neon-mcp",
      "args": ["--transport", "stdio"],
      "env": { "NEON_TOKEN": "paste-your-token-here" }
    }
  }
}
```

## Codex CLI

```bash
codex mcp add neon --env NEON_TOKEN="$NEON_TOKEN" -- neon-mcp --transport stdio
codex mcp list
```

This writes the server into `~/.codex/config.toml`[^codex-mcp]; restart running sessions.

## OpenCode

Add to `~/.config/opencode/opencode.json`[^opencode-mcp]:

```json
{
  "mcp": {
    "neon": {
      "type": "local",
      "command": ["/absolute/path/to/neon-mcp", "--transport", "stdio"],
      "enabled": true,
      "environment": { "NEON_TOKEN": "paste-your-token-here" }
    }
  }
}
```

## Google Antigravity

Add to `~/.gemini/config/mcp_config.json` (older installs: `~/.gemini/antigravity/mcp_config.json`):

```json
{
  "mcpServers": {
    "neon": {
      "command": "/absolute/path/to/neon-mcp",
      "args": ["--transport", "stdio"],
      "env": { "NEON_TOKEN": "paste-your-token-here" }
    }
  }
}
```

## Any other stdio client

Run `neon-mcp --transport stdio` (bare `neon-mcp` does the same) with the token in the
environment. The server speaks MCP 2026-07-28 and still accepts clients on earlier
protocol revisions over stdio.

## A hosted server (HTTP)

```bash
claude mcp add --transport http neon https://neon-mcp.example.org/mcp \
  --header "X-API-Token: $NEON_TOKEN"
```

Each user sends their own token in `X-API-Token`; the server honours it only over HTTPS
(see [Transports](../mcp/transports.md)). Over HTTP `neon_download_files` is not offered:
use the signed URLs from `neon_list_files` instead.

[^claude-code-mcp]: Claude Code — MCP. <https://docs.claude.com/en/docs/claude-code/mcp>
[^codex-mcp]: OpenAI Codex CLI. <https://developers.openai.com/codex/cli/>
[^opencode-mcp]: OpenCode — MCP servers. <https://opencode.ai/docs/mcp-servers/>
[^mesa-install]: idss-mesa installer. <https://github.com/idss-mesa/docs/blob/main/install.sh>
