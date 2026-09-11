---
title: "NEON API token"
description: "How to create a NEON API token step by step, why NEON's data and sample endpoints require it, how to give it to neon-mcp as NEON_TOKEN, how to check that NEON accepts it, and the rate limits with and without it."
type: Guide
tags:
  - getting-started
  - authentication
  - api-token
  - rate-limits
generated:
  by: "claude/opus-5"
  at: "2026-09-11T12:00:00Z"
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
  - id: neon-user-accounts
    resource: "https://www.neonscience.org/about/user-accounts"
    title: "NEON — Data Portal user accounts"
    author: "team:neon"
  - id: neon-token-tutorial
    resource: "https://www.neonscience.org/resources/learning-hub/tutorials/neon-api-tokens-tutorial"
    title: "NEON — Using an API token with neonUtilities"
    author: "team:neon"
  - id: neonutilities-python
    resource: "https://github.com/NEONScience/NEON-utilities-python"
    title: "neonutilities (Python) — README and examples"
    author: "team:neon"
status: stable
stale_after: "2027-03-11T00:00:00Z"
---

# NEON API token

neon-mcp needs no credentials for discovery: NEON's product, site, location,
release, taxonomy and prototype-dataset records are public. A **NEON API
token** is required only when a tool has to list or fetch actual data files
or trace samples. This page shows how to create a token, what to call it, how
to hand it to neon-mcp and how to check that NEON accepts it.

**In short:** sign in at the NEON Data Portal, open **My Account**, click
**GET API TOKEN**, copy the token, and put it in the environment neon-mcp starts
in as `NEON_TOKEN`. Then run `neon-mcp --check` and look for `"tokenAccepted": true`.

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

## Create a token

The token belongs to a free NEON Data Portal account[^neon-api-auth].

1. **Create an account (once).** On [data.neonscience.org](https://data.neonscience.org){target=_blank}
   click **Sign In** at the top right. Tick the box next to *I agree to the terms of
   service and privacy policy*, then choose a sign-up button: a Google account,
   CILogon (GitHub, ORCID or your university login), or an email address and
   password[^neon-user-accounts]. Finish any verification NEON asks for; tokens are
   issued only to authenticated, verified accounts[^neon-api-auth].
2. **Open My Account.** Signed in, go to
   [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}[^neon-myaccount].
3. **Generate the token.** Scroll to the bottom of the page and click
   **GET API TOKEN**. After a moment the token appears[^neon-token-tutorial].
4. **Copy it.** Click **Copy** next to the token[^neon-token-tutorial] and store it
   straight away where the next section says. A password manager is a good
   place to keep a second copy.

The same section of My Account lists your tokens. The **⋯** menu to the right of
a token disables or deletes it[^neon-user-accounts]. NEON documents no expiry
date. If a token may have leaked, disable or delete it and generate a new one[^neon-api-auth].

## Call it `NEON_TOKEN`

Store the token in an environment variable named **`NEON_TOKEN`**. That is the name
NEON's own tutorials use (in `.Renviron` for R, in a `.env` file for
Python)[^neon-token-tutorial], and the name the neonutilities examples read with
`os.environ.get("NEON_TOKEN")`[^neonutilities-python]. One variable then serves
neon-mcp, your neonUtilities scripts and `curl -H "X-API-Token: $NEON_TOKEN"`.
neonUtilities itself does not read the variable; you pass it as `token=`.
neon-mcp picks it up on its own.

| Variable | Read by neon-mcp? | Use it when |
| --- | --- | --- |
| `NEON_TOKEN` | yes | the normal case |
| `NEON_MCP_NEON__API_TOKEN` | yes, and it wins over `NEON_TOKEN` | neon-mcp should use a different token from your other NEON tools, or you configure everything through `NEON_MCP_*` variables |
| `NEON_API_TOKEN` | **no** | never: it is not a NEON convention. If it is the only one set, neon-mcp logs a warning; rename it to `NEON_TOKEN` |

## Give the token to neon-mcp

=== "Claude Code"

    ```bash
    read -rs NEON_TOKEN && export NEON_TOKEN     # paste the token, press Enter
    claude mcp add neon -s user -e NEON_TOKEN="$NEON_TOKEN" -- neon-mcp --transport stdio
    ```

    `read -rs` keeps the token out of the terminal and your shell history, unlike
    typing `export NEON_TOKEN=...`. The `-e` option copies the value into Claude Code's
    user configuration when you register the server. After replacing a token, run
    `claude mcp remove neon` and add the server again. Do not register with
    `-s project`: that writes `.mcp.json` into the repository, and the token with it.

=== "Desktop and JSON clients"

    Claude Desktop, OpenCode, Antigravity and similar clients take the variable in
    the server's `env` block of their own configuration file (see [Clients](clients.md)):

    ```json
    "env": { "NEON_TOKEN": "paste-your-token-here" }
    ```

    These files live in your home directory. Keep them out of dotfile repositories.

=== "A .env file"

    Put `NEON_TOKEN=paste-your-token-here` in a file named `.env`. neon-mcp does
    **not** read `.env` files by itself, so load it when you start a command:

    ```bash
    uv run --env-file .env neon-mcp --check     # uv loads the file for this command
    set -a; . ./.env; set +a                    # or export it into the current shell
    ```

    The neon-mcp repository's `.gitignore` already excludes `.env`. Anywhere else,
    add it to your own `.gitignore` first.

=== "YAML config file"

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
the process list and shell history. An environment variable wins over the YAML file.

!!! danger "Never commit a token"

    Do not paste a token into a repository, a checked-in MCP client
    configuration, an issue, or a chat transcript. If a token leaks, disable or
    delete it at [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}
    and generate a new one. neon-mcp sends it only as the `X-API-Token` header and
    only to data.neonscience.org, never logs it, never echoes it in tool results or
    error messages, never puts it in cache keys (only a one-way hash), and never
    places it in MCP `requestState` (which round-trips through the client).

## Check that NEON accepts it

Run the check in the same environment the server will run in:

```bash
neon-mcp --check
```

It makes one small NEON request and prints one line of JSON, for example
(`rateLimit` omitted here):

```json
{"ok": true, "version": "0.1.0", "tokenConfigured": true, "tokenAccepted": true, "apiReachable": true, "apiStatus": 200}
```

| `tokenConfigured` | `tokenAccepted` | Meaning |
| --- | --- | --- |
| `true` | `true` | NEON accepted the token. |
| `false` | `null` | neon-mcp found no token. Check the variable is spelled `NEON_TOKEN` and exported in the environment neon-mcp starts in, not only in another terminal. |
| `true` | `false` | NEON answered HTTP 403 and `problem` says so. The value is wrong (surrounding quotes, spaces, a partial copy) or the token was disabled or deleted. |

A rejected token is worse than none: NEON refuses *every* request that carries it,
public endpoints included, so discovery tools fail with `code: "forbidden"` until
you fix or unset it. Inside an agent, `neon_ping` with `check_api=true` reports the
same thing: `tokenConfigured`, `tokenSource`, and a note when NEON rejects the token.

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
  `code: "auth_required"`, whose message names `NEON_TOKEN` and links to
  [data.neonscience.org/myaccount](https://data.neonscience.org/myaccount){target=_blank}.
  The [tool reference](../tools/reference.md) marks each token-only tool, and
  `neon_ping` reports whether a token is available.

[^neon-api-auth]: NEON Data API — Authentication. <https://data.neonscience.org/data-api/authentication/>
[^neon-api-rate-limiting]: NEON Data API — Rate Limiting. <https://data.neonscience.org/data-api/rate-limiting/>
[^neon-myaccount]: NEON Data Portal — My Account. <https://data.neonscience.org/myaccount>
[^neon-user-accounts]: NEON — Data Portal user accounts. <https://www.neonscience.org/about/user-accounts>
[^neon-token-tutorial]: NEON — Using an API token with neonUtilities. <https://www.neonscience.org/resources/learning-hub/tutorials/neon-api-tokens-tutorial>
[^neonutilities-python]: neonutilities (Python) — README and examples. <https://github.com/NEONScience/NEON-utilities-python>
