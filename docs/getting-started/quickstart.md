---
title: "Quickstart"
description: "A first session with neon-mcp: register it with Claude Code, check it with neon_ping, then find a product, check availability, list files and cite."
type: Tutorial
tags:
  - getting-started
  - quickstart
  - tutorial
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: claude-code-mcp
    resource: "https://docs.claude.com/en/docs/claude-code/mcp"
    title: "Claude Code — MCP"
    author: "team:anthropic"
  - id: neon-api
    resource: "https://data.neonscience.org/data-api/"
    title: "NEON Data API"
    author: "team:neon"
status: stable
---

# Quickstart

This walks through a first session in Claude Code[^claude-code-mcp]; other clients
work the same way once connected ([Clients](clients.md)).

## 1. Register the server

For file listings, downloads and sample views you need a NEON API token. Create one
at [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}
(**GET API TOKEN**, then **Copy**; [step by step](api-token.md#create-a-token)) and
export it as `NEON_TOKEN`:

```bash
read -rs NEON_TOKEN && export NEON_TOKEN     # paste the token, press Enter
claude mcp add neon -s user -e NEON_TOKEN="$NEON_TOKEN" -- neon-mcp --transport stdio
```

Leave out `-e NEON_TOKEN=…` to start without a token; everything except file
listing, downloads and sample views works anonymously.

## 2. Check it

In a terminal, `neon-mcp --check` prints `"tokenAccepted": true` once NEON accepts
the token. Then ask the agent to "call neon_ping". The result shows the version,
protocol `2026-07-28`, whether a token is configured and whether downloads are enabled.

## 3. Five calls from question to citation

The agent normally chains these on its own; the arguments below are what it sends.
Results are abbreviated.

1. **Find the product**

    ```json
    {"tool": "neon_search_products", "arguments": {"query": "breeding bird point counts"}}
    ```

    → `DP1.10003.001` *Breeding landbird point counts*, with `nextSteps` suggesting
    `neon_get_availability(product='DP1.10003.001')`.

2. **Check availability** (no token)

    ```json
    {"tool": "neon_get_availability", "arguments": {"product": "DP1.10003.001", "domain_code": "D01"}}
    ```

    → one row per site in domain D01 with month ranges such as `"2015-05/2024-06"`,
    split by release in `byRelease` (`PROVISIONAL` months included and counted in
    `notes`).

3. **List the files** (token)

    ```json
    {"tool": "neon_list_files", "arguments": {"product": "DP1.10003.001", "site_codes": ["Harvard Forest"], "start_month": "2023-06", "kind": "data"}}
    ```

    → `resolved: [{"input": "Harvard Forest", "code": "HARV", ...}]` and the
    `brd_countdata`, `brd_perpoint` … CSVs with sizes, MD5s and signed URLs valid for
    about 7 days.

4. **Download** (stdio)

    ```json
    {"tool": "neon_download_files", "arguments": {"product": "DP1.10003.001", "site_codes": ["HARV"], "start_month": "2023-06", "kind": "data"}}
    ```

    → files under `~/neon-downloads/DP1.10003.001/HARV/2023-06/`, MD5-verified, with
    a `pandas.read_csv(...)` hint.

5. **Cite**

    ```json
    {"tool": "neon_get_citation", "arguments": {"product": "DP1.10003.001"}}
    ```

    → NEON-format text and BibTeX with the newest release DOI.

The `neon://guide/agent-workflow` resource carries the same recipe for agents.

[^claude-code-mcp]: Claude Code — MCP. <https://docs.claude.com/en/docs/claude-code/mcp>
[^neon-api]: NEON Data API. <https://data.neonscience.org/data-api/>
