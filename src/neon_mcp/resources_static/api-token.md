# NEON API token

Since NEON Data API 0.11.0 (June 2026) these endpoints return **HTTP 403**
without a token: data files and packages (`/data/...`), data queries
(`/data/query`), release-scoped data (`/releases/{tag}/data/...`), and sample
views and downloads (`/samples/view`, `/samples/download`). Everything else —
products, sites, locations, availability, taxonomy, releases, prototype
datasets and GraphQL — works anonymously.

In neon-mcp this means `neon_list_files`, `neon_download_files` (data files)
and `neon_get_sample` need a token; every other tool works without one.

## Get a token

Sign in at <https://data.neonscience.org/myaccount> and create an API token.
Treat it like a password: never commit it or paste it into a chat.

## Give it to neon-mcp

* **stdio** (Claude Code, Claude Desktop, Codex, OpenCode): set
  `NEON_MCP_NEON__API_TOKEN` in the server's environment. `NEON_TOKEN` (the
  variable neonUtilities documents) and `NEON_API_TOKEN` are accepted as
  fallbacks. Example: `claude mcp add neon -s user -e NEON_TOKEN=... -- neon-mcp`.
* **HTTP** (hosted): each caller sends its own token in the `X-API-Token`
  header. The server honours it only when its `public_base_url` is `https://`
  (TLS in front), so tokens never travel in clear text. The operator's own
  token is not lent to anonymous callers unless
  `share_config_token_over_http` is set.

neon-mcp sends the token only as the `X-API-Token` header, only to
data.neonscience.org, and never logs, caches or echoes it.

## Rate limits

| | Burst | Sustained |
|---|---|---|
| Anonymous (per IP) | 200 requests | 2 per second |
| With a token | 2000 requests | 8 per second |

neon-mcp keeps 10 % under these limits, reads `X-RateLimit-*` headers, and
retries HTTP 429 after NEON's `RetryAfter`. `neon_ping` reports the remaining budget.
