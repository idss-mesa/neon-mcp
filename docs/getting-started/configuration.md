---
title: "Configuration"
description: "Configure neon-mcp with a YAML file, NEON_MCP_ environment variables or command-line flags; precedence rules and every setting with its default."
type: Reference
tags:
  - getting-started
  - configuration
  - environment
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: config-module
    resource: "https://github.com/idss-mesa/neon-mcp/blob/main/src/neon_mcp/config.py"
    title: "neon-mcp configuration model (config.py)"
    author: "team:idss-mesa"
status: stable
---

# Configuration

neon-mcp runs with no configuration at all: the defaults serve stdio, keep 10 %
under NEON's rate limits, cache responses in memory and confine downloads to
`~/neon-downloads`. Settings come from four layers; a higher layer wins:

1. **Command-line flags** (only a handful of common settings).
2. **Environment variables** named `NEON_MCP_<SECTION>__<FIELD>`, with a double
   underscore descending into nested sections at any depth, e.g.
   `NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_RPS=1.5`. List settings take a
   comma-separated value: `NEON_MCP_SERVER__ALLOWED_HOSTS=neon.example.org,alt.example.org`.
   The empty string, `none` and `null` mean "unset".
3. **A YAML file** passed with `--config path.yaml`, using the same section and
   field names (see `config.yaml.example` in the repository).
4. **Built-in defaults** (the table below).

Unknown keys in the YAML file or the environment are ignored with a warning, so a
typo does not stop the server but is visible in its log.

## The NEON API token

The token is the only secret. Set `NEON_MCP_NEON__API_TOKEN`; if that is unset,
neon-mcp falls back to `NEON_TOKEN` (the variable neonUtilities documents) and then
`NEON_API_TOKEN`. There is deliberately **no command-line flag** for it: arguments are
visible to every user in the process list and end up in shell history. See
[NEON API token](api-token.md).

## Command-line flags

| Flag | Sets |
| --- | --- |
| `--config PATH` | YAML file to load |
| `--transport {stdio,http}` | `server.transport` |
| `--bind-address`, `--bind-port` | `server.bind_address`, `server.bind_port` |
| `--log-level` | `server.log_level` |
| `--download-dir PATH` | `downloads.directory` |
| `--no-downloads` | `downloads.enabled = false` |
| `--prewarm` / `--no-prewarm` | `cache.prewarm` |
| `--print-config` | print the effective configuration (token shown as `***`) and exit |
| `--check` | load the configuration, call `neon_ping(check_api=true)` in-process, print a JSON verdict, exit 0 or 1 |
| `--version` | print the version |

## Automatic values

A few settings default to "unset" and resolve per transport:

* `neon.token_for_public_endpoints` — on stdio the token is sent to every NEON
  request (a single user gets the faster token rate limit everywhere); over HTTP it
  is sent only to token-only endpoints.
* `cache.prewarm` — HTTP deployments build the product and site catalogs at startup
  (`/readyz` reports `warming` until done); stdio builds them lazily.
* `downloads.enabled` — downloads exist only on stdio; over HTTP the download tool is
  not listed at all.

## All settings

<!-- BEGIN GENERATED CONFIG (scripts/gen_config_reference.py; do not edit) -->

| Setting (YAML path) | Environment variable | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `neon.base_url` | `NEON_MCP_NEON__BASE_URL` | str | `https://data.neonscience.org/api/v0` | NEON REST API base URL. |
| `neon.graphql_url` | `NEON_MCP_NEON__GRAPHQL_URL` | str | `https://data.neonscience.org/graphql` | NEON GraphQL endpoint (not under /api/v0). |
| `neon.api_token` | `NEON_MCP_NEON__API_TOKEN`<br>(or `NEON_TOKEN`, `NEON_API_TOKEN`) | SecretStr \| null | unset | NEON API token (https://data.neonscience.org/myaccount). Required for data files, data queries and sample views. Prefer the env var; never commit it. Fallbacks: NEON_TOKEN, NEON_API_TOKEN. |
| `neon.token_for_public_endpoints` | `NEON_MCP_NEON__TOKEN_FOR_PUBLIC_ENDPOINTS` | bool \| null | unset | Also send the token to public endpoints (raises the rate limit). Unset: true on stdio, false on http. |
| `neon.user_agent_suffix` | `NEON_MCP_NEON__USER_AGENT_SUFFIX` | str \| null | unset | Text appended to the User-Agent header. |
| `neon.connect_timeout_s` | `NEON_MCP_NEON__CONNECT_TIMEOUT_S` | float | `10.0` | TCP/TLS connect timeout. |
| `neon.read_timeout_s` | `NEON_MCP_NEON__READ_TIMEOUT_S` | float | `60.0` | Default read timeout. |
| `neon.catalog_read_timeout_s` | `NEON_MCP_NEON__CATALOG_READ_TIMEOUT_S` | float | `180.0` | Read timeout for catalog-sized fetches (product/site lists). |
| `neon.download_read_timeout_s` | `NEON_MCP_NEON__DOWNLOAD_READ_TIMEOUT_S` | float | `300.0` | Read timeout for file downloads. |
| `neon.max_concurrency` | `NEON_MCP_NEON__MAX_CONCURRENCY` | int | `4` | Maximum simultaneous upstream requests. |
| `neon.prefer_graphql` | `NEON_MCP_NEON__PREFER_GRAPHQL` | bool | `true` | Build catalogs and availability from GraphQL (REST is the fallback). |
| `neon.graphql_breaker_failures` | `NEON_MCP_NEON__GRAPHQL_BREAKER_FAILURES` | int | `2` | Consecutive GraphQL failures that open the circuit breaker. |
| `neon.graphql_breaker_cooldown_s` | `NEON_MCP_NEON__GRAPHQL_BREAKER_COOLDOWN_S` | float | `900.0` | How long an open GraphQL breaker routes everything to REST. |
| `neon.rate_limit.anonymous_burst` | `NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_BURST` | int | `180` | Burst size for anonymous requests (NEON: 200 per IP). |
| `neon.rate_limit.anonymous_rps` | `NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_RPS` | float | `1.8` | Sustained requests/second without a token (NEON: 2). |
| `neon.rate_limit.token_burst` | `NEON_MCP_NEON__RATE_LIMIT__TOKEN_BURST` | int | `1800` | Burst size for requests carrying a token (NEON: 2000). |
| `neon.rate_limit.token_rps` | `NEON_MCP_NEON__RATE_LIMIT__TOKEN_RPS` | float | `7.2` | Sustained requests/second with a token (NEON: 8). |
| `neon.rate_limit.low_water` | `NEON_MCP_NEON__RATE_LIMIT__LOW_WATER` | int | `5` | When X-RateLimit-Remaining falls to this value, wait for the reset. |
| `neon.rate_limit.max_wait_s` | `NEON_MCP_NEON__RATE_LIMIT__MAX_WAIT_S` | float | `10.0` | Longest the client sleeps for rate-limit headroom before failing with rate_limited. |
| `neon.retries.max_attempts` | `NEON_MCP_NEON__RETRIES__MAX_ATTEMPTS` | int | `3` | Attempts per upstream call, including the first. |
| `neon.retries.backoff_base_s` | `NEON_MCP_NEON__RETRIES__BACKOFF_BASE_S` | float | `0.5` | Base of the exponential backoff (0.5 * 2^n seconds). |
| `neon.retries.backoff_max_s` | `NEON_MCP_NEON__RETRIES__BACKOFF_MAX_S` | float | `8.0` | Cap on a single backoff sleep. |
| `neon.retries.retry_after_default_s` | `NEON_MCP_NEON__RETRIES__RETRY_AFTER_DEFAULT_S` | float | `1.0` | Wait used on HTTP 429 when NEON sends no RetryAfter header. |
| `cache.enabled` | `NEON_MCP_CACHE__ENABLED` | bool | `true` | Cache upstream responses in memory. |
| `cache.max_entries` | `NEON_MCP_CACHE__MAX_ENTRIES` | int | `1024` | Overall entry cap across families. |
| `cache.max_index_entries` | `NEON_MCP_CACHE__MAX_INDEX_ENTRIES` | int | `4` | Cap on built catalog index objects (one per release). |
| `cache.prewarm` | `NEON_MCP_CACHE__PREWARM` | bool \| null | unset | Build the catalogs at startup. Unset: true on http, false on stdio. |
| `cache.refresh_ahead` | `NEON_MCP_CACHE__REFRESH_AHEAD` | float | `0.1` | Fraction of a TTL before expiry at which http mode refreshes in the background. |
| `cache.stale_if_error_s` | `NEON_MCP_CACHE__STALE_IF_ERROR_S` | int | `86400` | How long an expired entry may be served when a refresh fails. |
| `cache.ttl_s.catalog` | `NEON_MCP_CACHE__TTL_S__CATALOG` | int | `3600` | Product/site catalogs, releases list, prototype list, site locations. |
| `cache.ttl_s.detail` | `NEON_MCP_CACHE__TTL_S__DETAIL` | int | `900` | Single product/site/release detail and GraphQL availability. |
| `cache.ttl_s.locations` | `NEON_MCP_CACHE__TTL_S__LOCATIONS` | int | `21600` | Location records and hierarchies. |
| `cache.ttl_s.releases` | `NEON_MCP_CACHE__TTL_S__RELEASES` | int | `21600` | Release records. |
| `cache.ttl_s.taxonomy` | `NEON_MCP_CACHE__TTL_S__TAXONOMY` | int | `86400` | Taxonomy pages. |
| `cache.ttl_s.samples_classes` | `NEON_MCP_CACHE__TTL_S__SAMPLES_CLASSES` | int | `86400` | Sample-class lists. |
| `cache.ttl_s.samples_view` | `NEON_MCP_CACHE__TTL_S__SAMPLES_VIEW` | int | `60` | Sample views (token-scoped). |
| `cache.ttl_s.data` | `NEON_MCP_CACHE__TTL_S__DATA` | int | `600` | Data-file listings (signed URLs live 7 days). |
| `cache.ttl_s.prototype` | `NEON_MCP_CACHE__TTL_S__PROTOTYPE` | int | `21600` | Prototype dataset records. |
| `cache.ttl_s.documents` | `NEON_MCP_CACHE__TTL_S__DOCUMENTS` | int | `86400` | Document metadata and extracted text. |
| `limits.default_limit` | `NEON_MCP_LIMITS__DEFAULT_LIMIT` | int | `50` | Default page size where a tool does not set its own. |
| `limits.max_limit` | `NEON_MCP_LIMITS__MAX_LIMIT` | int | `500` | Largest page size any tool accepts. |
| `limits.max_result_bytes` | `NEON_MCP_LIMITS__MAX_RESULT_BYTES` | int | `50000` | Tool results are trimmed (with page.truncated) to fit this many bytes of compact JSON. |
| `limits.hard_max_result_bytes` | `NEON_MCP_LIMITS__HARD_MAX_RESULT_BYTES` | int | `200000` | A result still larger than this after trimming fails with result_too_large. |
| `limits.text_budget_summary` | `NEON_MCP_LIMITS__TEXT_BUDGET_SUMMARY` | int | `300` | Characters kept of long text fields in summaries. |
| `limits.text_budget_detail` | `NEON_MCP_LIMITS__TEXT_BUDGET_DETAIL` | int | `4000` | Default characters kept of long text fields in detail views. |
| `limits.max_sites_per_call` | `NEON_MCP_LIMITS__MAX_SITES_PER_CALL` | int | `30` | Most sites one neon_list_files / neon_download_files call accepts. |
| `limits.max_site_months_per_query` | `NEON_MCP_LIMITS__MAX_SITE_MONTHS_PER_QUERY` | int | `500` | Largest sites x months product a data query may span. |
| `limits.max_location_roots` | `NEON_MCP_LIMITS__MAX_LOCATION_ROOTS` | int | `20` | Most site codes one neon_find_locations call walks. |
| `limits.graphql_max_query_chars` | `NEON_MCP_LIMITS__GRAPHQL_MAX_QUERY_CHARS` | int | `8000` | Longest query neon_graphql accepts. |
| `limits.graphql_max_depth` | `NEON_MCP_LIMITS__GRAPHQL_MAX_DEPTH` | int | `8` | Deepest selection set neon_graphql accepts. |
| `limits.graphql_max_response_bytes` | `NEON_MCP_LIMITS__GRAPHQL_MAX_RESPONSE_BYTES` | int | `50000` | Default neon_graphql response budget. |
| `limits.graphql_hard_max_response_bytes` | `NEON_MCP_LIMITS__GRAPHQL_HARD_MAX_RESPONSE_BYTES` | int | `200000` | Largest max_bytes a neon_graphql caller may request. |
| `limits.max_document_bytes` | `NEON_MCP_LIMITS__MAX_DOCUMENT_BYTES` | int | `26214400` | Largest document neon_get_document extracts text from (in memory). |
| `limits.tools_list_max_bytes` | `NEON_MCP_LIMITS__TOOLS_LIST_MAX_BYTES` | int | `135000` | Conformance bound on the serialized tools/list result (measured 107,734 B with 20 tools, x1.25). |
| `downloads.enabled` | `NEON_MCP_DOWNLOADS__ENABLED` | bool \| null | unset | Offer neon_download_files. Unset: true on stdio; never available over http. |
| `downloads.directory` | `NEON_MCP_DOWNLOADS__DIRECTORY` | Path | `~/neon-downloads` | Directory every download is confined to (created on first use). |
| `downloads.max_files_per_call` | `NEON_MCP_DOWNLOADS__MAX_FILES_PER_CALL` | int | `50` | Most files one neon_download_files call transfers. |
| `downloads.max_bytes_per_call` | `NEON_MCP_DOWNLOADS__MAX_BYTES_PER_CALL` | int | `2147483648` | Most bytes one neon_download_files call transfers. |
| `downloads.max_file_bytes` | `NEON_MCP_DOWNLOADS__MAX_FILE_BYTES` | int | `1073741824` | Largest single file neon_download_files accepts. |
| `downloads.verify_checksums` | `NEON_MCP_DOWNLOADS__VERIFY_CHECKSUMS` | bool | `true` | Verify MD5 checksums NEON publishes. |
| `downloads.allowed_hosts` | `NEON_MCP_DOWNLOADS__ALLOWED_HOSTS` | list[str] | `[data.neonscience.org, storage.googleapis.com, *.storage.googleapis.com]` | Hosts downloads (and their redirects) may come from; '*.' is a subdomain wildcard. |
| `server.transport` | `NEON_MCP_SERVER__TRANSPORT` | `stdio` \| `http` | `stdio` | stdio (local clients) or http (stateless Streamable HTTP at /mcp). |
| `server.bind_address` | `NEON_MCP_SERVER__BIND_ADDRESS` | str | `127.0.0.1` | HTTP bind address. |
| `server.bind_port` | `NEON_MCP_SERVER__BIND_PORT` | int | `8080` | HTTP bind port. |
| `server.public_base_url` | `NEON_MCP_SERVER__PUBLIC_BASE_URL` | str \| null | unset | Public URL of a hosted deployment; its host/origin join the allow-lists and https:// enables per-request tokens. |
| `server.allowed_hosts` | `NEON_MCP_SERVER__ALLOWED_HOSTS` | list[str] | `[]` | Host header allow-list (DNS-rebinding protection). |
| `server.allowed_origins` | `NEON_MCP_SERVER__ALLOWED_ORIGINS` | list[str] | `[]` | Origin header allow-list (DNS-rebinding protection). |
| `server.dns_rebinding_protection` | `NEON_MCP_SERVER__DNS_REBINDING_PROTECTION` | bool \| null | unset | Force DNS-rebinding protection on/off. Unset: SDK default (on for loopback binds or when allow-lists are set). |
| `server.json_response` | `NEON_MCP_SERVER__JSON_RESPONSE` | bool | `false` | Answer POST /mcp with application/json instead of a single SSE frame. |
| `server.max_request_body_size` | `NEON_MCP_SERVER__MAX_REQUEST_BODY_SIZE` | int | `1048576` | Largest accepted request body in bytes. |
| `server.accept_header_token` | `NEON_MCP_SERVER__ACCEPT_HEADER_TOKEN` | bool | `true` | HTTP: honour a per-request NEON token header (subject to the TLS gate). |
| `server.request_token_header` | `NEON_MCP_SERVER__REQUEST_TOKEN_HEADER` | str | `X-API-Token` | Header carrying a caller's NEON token in HTTP mode. |
| `server.allow_insecure_header_token` | `NEON_MCP_SERVER__ALLOW_INSECURE_HEADER_TOKEN` | bool | `false` | Accept header tokens when public_base_url is not https:// (development only). |
| `server.share_config_token_over_http` | `NEON_MCP_SERVER__SHARE_CONFIG_TOKEN_OVER_HTTP` | bool | `false` | Lend the operator's configured token to anonymous HTTP callers (private deployments only). |
| `server.tools_list_ttl_ms` | `NEON_MCP_SERVER__TOOLS_LIST_TTL_MS` | int | `300000` | ttlMs advertised on tools/list. |
| `server.log_level` | `NEON_MCP_SERVER__LOG_LEVEL` | `debug` \| `info` \| `warning` \| `error` \| `critical` | `info` | Log verbosity. |
| `server.instructions_extra` | `NEON_MCP_SERVER__INSTRUCTIONS_EXTRA` | str \| null | unset | Text appended to the server instructions. |

<!-- END GENERATED CONFIG -->
