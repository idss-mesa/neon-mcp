# NEON API token

Since NEON Data API 0.11.0 (June 2026) these endpoints return **HTTP 403**
without a token: data files and packages (`/data/...`), data queries
(`/data/query`), release-scoped data (`/releases/{tag}/data/...`), and sample
views and downloads (`/samples/view`, `/samples/download`). Everything else —
products, sites, locations, availability, taxonomy, releases, prototype
datasets and GraphQL — works anonymously.

In neon-mcp this means `neon_list_files`, `neon_download_files` (data files)
and `neon_get_sample` need a token; every other tool works without one.

## Create a token (the user does this, not the agent)

1. Create a free account: on <https://data.neonscience.org> click **Sign In**
   (Google, CILogon for GitHub/ORCID/university logins, or email).
2. Open **My Account**: <https://data.neonscience.org/myaccount>.
3. At the bottom of the page click **GET API TOKEN**, then **Copy**.

Treat it like a password: never commit it or paste it into a chat. The **⋯** menu
next to a token on My Account disables or deletes it.

## Give it to neon-mcp

* **stdio** (Claude Code, Claude Desktop, Codex, OpenCode): set **`NEON_TOKEN`**
  (the name NEON's own tutorials use) in the server's environment, e.g.
  `claude mcp add neon -s user -e NEON_TOKEN="$NEON_TOKEN" -- neon-mcp`.
  `NEON_MCP_NEON__API_TOKEN` overrides it. `NEON_API_TOKEN` is **not** read.
  neon-mcp does not load `.env` files itself (`uv run --env-file .env ...` does).
* **HTTP** (hosted): each caller sends its own token in the `X-API-Token`
  header. The server honours it only when its `public_base_url` is `https://`
  (TLS in front), so tokens never travel in clear text. The operator's own
  token is not lent to anonymous callers unless
  `share_config_token_over_http` is set.

## Check it

`neon_ping(check_api=true)` reports `tokenConfigured` and `tokenSource`, and adds a
note when NEON rejects the token. In a terminal, `neon-mcp --check` prints
`tokenAccepted`. A rejected token (mistyped, disabled or deleted) makes NEON refuse
**every** request that carries it, public ones included (`code: "forbidden"`): the
user must fix or unset it.

neon-mcp sends the token only as the `X-API-Token` header, only to
data.neonscience.org, and never logs, caches or echoes it.

## Rate limits

| | Burst | Sustained |
|---|---|---|
| Anonymous (per IP) | 200 requests | 2 per second |
| With a token | 2000 requests | 8 per second |

neon-mcp keeps 10 % under these limits, reads `X-RateLimit-*` headers, and
retries HTTP 429 after NEON's `RetryAfter`. `neon_ping` reports the remaining budget.
