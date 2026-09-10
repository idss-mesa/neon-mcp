# neon-mcp

[![CI](https://github.com/idss-mesa/neon-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/idss-mesa/neon-mcp/actions/workflows/ci.yml)
[![Docs](https://github.com/idss-mesa/neon-mcp/actions/workflows/docs.yml/badge.svg)](https://idss-mesa.github.io/neon-mcp/)
[![MCP 2026-07-28](https://img.shields.io/badge/MCP-2026--07--28-2e7d32)](https://modelcontextprotocol.io/specification/2026-07-28)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

A [Model Context Protocol](https://modelcontextprotocol.io/) server for the
[NEON Data API](https://data.neonscience.org/data-api/) — the National Ecological
Observatory Network's 200 data products at 81 field sites. It lets AI agents find
products and sites, check which months have data (released and provisional), list
and download data files, walk location hierarchies, browse releases, taxonomy,
samples and prototype datasets, and cite what they use — through compact,
paginated, schema-validated tool results instead of NEON's multi-megabyte payloads.

- **MCP 2026-07-28** stateless core on the Python `mcp` 2.x SDK; stdio (both protocol
  eras) and stateless Streamable HTTP at `/mcp`.
- **20 tools**, 8 `neon://` resources + 3 templates, 3 prompts.
- **Token-aware**: discovery works anonymously; data files and sample views use your
  NEON API token (required by NEON since June 2026), never logged or echoed.
- **Rate-limit and size aware**: per-identity throttling under NEON's limits, caching,
  GraphQL-first catalogs, a 50 KB result budget with explicit paging.

Documentation: **https://idss-mesa.github.io/neon-mcp/** (also as
[llms.txt](https://idss-mesa.github.io/neon-mcp/llms.txt) and
[llms-full.txt](https://idss-mesa.github.io/neon-mcp/llms-full.txt) for agents).

## Quick start

```bash
uv tool install git+https://github.com/idss-mesa/neon-mcp     # PyPI release pending
neon-mcp --check                                               # {"ok": true, ...}
claude mcp add neon -s user -e NEON_TOKEN="$NEON_TOKEN" -- neon-mcp --transport stdio
```

Then ask your agent to call `neon_ping`, or to "find NEON breeding bird data at
Harvard Forest for June 2023 and cite it".

## NEON API token

Create one at <https://data.neonscience.org/myaccount>. Set `NEON_MCP_NEON__API_TOKEN`
(or `NEON_TOKEN`) in the server's environment. Without a token everything works except
`neon_list_files`, `neon_download_files` (for data files) and `neon_get_sample`, which
return `auth_required`. Hosted deployments accept each caller's token in the
`X-API-Token` header behind HTTPS. Never commit a token.

## Clients

| Client | Registration |
| --- | --- |
| Claude Code | `claude mcp add neon -s user -- neon-mcp --transport stdio` |
| Claude Code (hosted) | `claude mcp add --transport http neon https://host/mcp --header "X-API-Token: $NEON_TOKEN"` |
| Codex CLI | `codex mcp add neon --env NEON_TOKEN=... -- neon-mcp --transport stdio` |
| Claude Desktop, OpenCode, Antigravity | JSON snippets in [Clients](https://idss-mesa.github.io/neon-mcp/getting-started/clients/) |

## Tools

| Family | Tools |
| --- | --- |
| Products and sites | `neon_search_products`, `neon_get_product`, `neon_search_sites`, `neon_get_site` |
| Availability and data | `neon_get_availability`, `neon_list_files`, `neon_download_files` (stdio) |
| Locations | `neon_find_locations`, `neon_get_location` |
| Releases and citation | `neon_list_releases`, `neon_get_release`, `neon_get_citation` |
| Taxonomy, samples, prototype | `neon_search_taxonomy`, `neon_list_sample_classes`, `neon_get_sample`, `neon_search_prototype_datasets`, `neon_get_prototype_dataset` |
| Utilities | `neon_ping`, `neon_get_document`, `neon_graphql` |

Inputs, result fields and endpoints: [tool reference](docs/tools/reference.md)
(generated from the registry).

## Configuration and deployment

YAML (`--config`), `NEON_MCP_<SECTION>__<FIELD>` environment variables and flags; see
[Configuration](https://idss-mesa.github.io/neon-mcp/getting-started/configuration/),
`config.yaml.example` and `.env.example`. For a hosted server:
`neon-mcp --transport http` behind TLS, or the included `Dockerfile` — see
[Hosted HTTP deployment](https://idss-mesa.github.io/neon-mcp/deploy/hosted-http/).

## Development

```bash
git clone https://github.com/idss-mesa/neon-mcp && cd neon-mcp
uv sync --all-extras
uv run pytest && uv run mypy --strict src && uv run ruff check src tests scripts
```

See `CLAUDE.md`, `AGENTS.md` (documentation rules) and
[Contributing](https://idss-mesa.github.io/neon-mcp/develop/contributing/).

## Citing NEON data and license

NEON data are CC BY 4.0; cite each product at its release DOI (`neon_get_citation` does
this) — see [Citing NEON data](https://idss-mesa.github.io/neon-mcp/about/citing-neon/).
neon-mcp is MIT-licensed, Copyright (c) 2026 The Regents of the University of New Mexico,
and is not affiliated with NEON, Battelle or NSF.
