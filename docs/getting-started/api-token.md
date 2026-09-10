---
title: "NEON API token"
description: "Why NEON's data and sample endpoints require an API token, how to obtain one, how neon-mcp reads it, and the rate limits that apply with and without it."
type: Guide
tags:
  - getting-started
  - authentication
  - api-token
  - rate-limits
generated:
  by: "claude/fable-5.1"
  at: "2026-09-10T12:00:00Z"
sources:
  - id: neon-api-auth
    resource: "https://data.neonscience.org/data-api/authentication/"
    title: "NEON Data API — Authentication"
    author: "team:neon"
  - id: neon-api-rate-limiting
    resource: "https://data.neonscience.org/data-api/rate-limiting/"
    title: "NEON Data API — Rate Limiting"
    author: "team:neon"
  - id: neon-myaccount
    resource: "https://data.neonscience.org/myaccount"
    title: "NEON Data Portal — My Account (API tokens)"
    author: "team:neon"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# NEON API token

neon-mcp needs no credentials for discovery: NEON's product, site, location,
release, taxonomy and prototype-dataset records are public. A **NEON API
token** is required only when a tool has to list or fetch actual data files
or trace samples. This page explains why, where to get a token, how to hand
it to neon-mcp, and what changes once it is set.

## Why a token is needed

Since version 0.11.0 of the NEON Data API (June 2026) the following
endpoints are marked *Requires Authentication*. Without a token they answer
`HTTP 403` with the body
`{"error":{"status":403,"detail":"Access Denied"},"data":null}`[^neon-api-auth]:

| Endpoint family | Paths |
| --- | --- |
| Data files | `GET /data/{productCode}/{siteCode}/{year-month}` (and `/{filename}`), `GET /data/package/{productCode}/{siteCode}/{year-month}` |
| Data query | `GET /data/query`, `POST /data/query` |
| Release-pinned data | `GET /releases/{releaseTag}/data/...` (all variants) |
| Sample tracking | `GET /samples/view`, `GET /samples/download` |

Everything else — `/products`, `/sites`, `/locations`, `/releases` (list,
detail, products, sites), `/taxonomy`, `/samples/classes`,
`/samples/supportedClasses`, `/prototype/*` and the GraphQL endpoint — is
anonymous. Data availability per site and month is part of the public product
and site records, so neon-mcp can tell you *what* exists without a token; it
needs the token to tell you *where the files are* and to fetch them.

## Getting a token

1. Sign in (or create a free account) at the NEON Data Portal:
   [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}[^neon-myaccount].
2. In **My Account**, open the API tokens section and generate a token.
3. Copy it somewhere safe and treat it exactly like a password.

NEON accepts the token either as the `X-API-Token` request header or as an
`apiToken` query parameter[^neon-api-auth]. neon-mcp always sends the header
form, so the token never appears in request URLs, access logs or the signed
download links it returns.

## Giving the token to neon-mcp

=== "Local (stdio) — environment variable"

    ```bash
    export NEON_MCP_NEON__API_TOKEN="paste-your-token-here"
    # or the variable neonUtilities documents, accepted as a fallback:
    export NEON_TOKEN="paste-your-token-here"
    ```

    neon-mcp reads `NEON_MCP_NEON__API_TOKEN` first, then `NEON_TOKEN`, then
    `NEON_API_TOKEN`. Pass it to a client at registration, e.g.
    `claude mcp add neon -s user -e NEON_TOKEN=... -- neon-mcp --transport stdio`,
    or through a systemd `EnvironmentFile=`.

=== "Local (stdio) — YAML config file"

    ```yaml
    neon:
      api_token: "paste-your-token-here"
    ```

    Pass the file with `--config`. Keep it out of version control — `config.yaml`
    and `*.local.yaml` are already in the repository's `.gitignore`.

=== "Hosted (HTTP) — per-request header"

    Each caller sends its own token in the `X-API-Token` header, for example
    `claude mcp add --transport http neon https://neon-mcp.example.org/mcp --header "X-API-Token: $NEON_TOKEN"`.
    The server honours the header only when its `server.public_base_url` is
    `https://` (TLS in front of it), so a token never crosses the network in clear
    text; `server.allow_insecure_header_token` overrides this for local testing only.
    An operator's configured token is **not** lent to anonymous HTTP callers unless
    `server.share_config_token_over_http` is set.

There is deliberately no command-line flag for the token: arguments are visible in
the process list and shell history. The environment variable wins over the YAML file.

!!! danger "Never commit a token"

    Do not paste a token into a repository, a checked-in MCP client
    configuration, an issue, or a chat transcript. If a token leaks, revoke
    it at [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}
    and generate a new one. neon-mcp sends it only as the `X-API-Token` header and
    only to data.neonscience.org, never logs it, never echoes it in tool results or
    error messages, never puts it in cache keys (only a one-way hash), and never
    places it in MCP `requestState` (which round-trips through the client).

## Rate limits

NEON rate-limits the API globally across all endpoints. Each limit has a
*burst* (requests you can make at once) and a *rate* at which the burst
refills. A token raises both substantially[^neon-api-rate-limiting]:

| Mode | Burst | Sustained rate | Applied per |
| --- | --- | --- | --- |
| Anonymous | 200 requests | 2 requests/s | IP address |
| With API token | 2 000 requests | 8 requests/s | token |

Every response carries `X-RateLimit-Limit` (the burst), `X-RateLimit-Remaining`
and `X-RateLimit-Reset` (seconds until the burst refills in full). When the
limit is exceeded the API returns `HTTP 429` with a `RetryAfter` header and
the body `{"message":"API rate limit exceeded"}`. neon-mcp shares one HTTP
client across all tools, slows down when `X-RateLimit-Remaining` runs low,
and retries a 429 after the `RetryAfter` interval (it keeps 10 % under both limits), so agents rarely hit the
limit — but a token remains the single most effective way to speed up a
heavy session.

NEON reserves the right to change these limits at any time; the response
headers are authoritative[^neon-api-rate-limiting].

## What happens without a token

* Discovery tools (products, sites, locations, availability, releases,
  taxonomy, prototype datasets) behave identically with or without a token,
  apart from the lower rate limit.
* Three tools need a token: `neon_list_files`, `neon_download_files` (for NEON data
  files; prototype and document downloads need none) and `neon_get_sample`. Without
  one they fail **before** any request with a structured error,
  `code: "auth_required"`, whose message names the settings above and links to
  [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}.
  The [tool reference](../tools/reference.md) marks each token-only tool, and
  `neon_ping` reports whether a token is available.

[^neon-api-auth]: NEON Data API — Authentication. <https://data.neonscience.org/data-api/authentication/>
[^neon-api-rate-limiting]: NEON Data API — Rate Limiting. <https://data.neonscience.org/data-api/rate-limiting/>
[^neon-myaccount]: NEON Data Portal — My Account. <https://data.neonscience.org/myaccount>
