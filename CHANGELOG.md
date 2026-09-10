# Changelog

All notable changes to the neon-mcp package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Documentation changes are logged
separately in `docs/log.md`.

## [0.1.0] - 2026-09-10

First release. Supersedes the TypeScript server in `tyson-swetnam/neon-data-api`
(`mcp/`, MCP SDK 1.x, protocol 2024-11-05, 15 tools).

### Added

- MCP **2026-07-28** stateless-core server on the Python `mcp` 2.x SDK: stdio
  (dual-era, legacy clients still work) and stateless Streamable HTTP at `/mcp`
  with `/healthz` and `/readyz`; no SSE, no sessions.
- 20 tools (19 over HTTP): products (search, detail with opt-in sections), sites
  (search, detail), availability (GraphQL-windowed month ranges per release,
  provisional include/exclude/only), locations (hierarchy walks by type, detail),
  data files (listing, stdio downloads with plan-before-transfer and MD5
  verification), releases, citations (NEON wording, BibTeX), taxonomy, sample
  classes and custody chains (MRTR class disambiguation), prototype datasets,
  documents (in-memory PDF text), a guard-railed GraphQL tool, and `neon_ping`.
- 8 `neon://` resources, 3 resource templates, 3 prompts; server instructions.
- NEON API token support (required by NEON since API 0.11.0 for data files, data
  queries and sample views): `NEON_MCP_NEON__API_TOKEN` / `NEON_TOKEN` on stdio,
  per-request `X-API-Token` over HTTPS for hosted deployments; never logged.
- Per-identity rate limiting 10 % under NEON's limits, 429/5xx retries, an
  in-memory TTL cache with single-flight and stale-if-error, GraphQL-first
  catalogs with REST fallback and a circuit breaker.
- Hermetic test suite over recorded NEON fixtures, an MCP 2026-07-28 conformance
  suite, and a real stdio subprocess test for both protocol eras.
- OKF v0.2 documentation bundle rendered with Zensical to
  https://idss-mesa.github.io/neon-mcp/ with an agent surface (`llms.txt`,
  `llms-full.txt`, per-page Markdown, `robots.txt`).
