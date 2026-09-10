# CLAUDE.md — neon-mcp

neon-mcp is a Model Context Protocol server (MCP **2026-07-28**, stateless core)
for the NEON Data API, published at https://github.com/idss-mesa/neon-mcp with
documentation at https://idss-mesa.github.io/neon-mcp/. Python 3.11+, `mcp>=2.0,<3`
(low-level `Server`), pydantic v2, httpx, structlog. House style follows
`idss-mesa/mesa-mcp`. `DESIGN.md` records every decision (the D-numbers) and
`RESEARCH.md` the verified API facts; read them before changing behaviour.

## Commands

```bash
uv sync --all-extras
uv run pytest                                   # hermetic unit + conformance tests
uv run ruff check src tests scripts && uv run ruff format --check src tests
uv run mypy --strict src
uv run neon-mcp --check                         # config + one live NEON request
NEON_MCP_LIVE=1 NEON_TOKEN=... uv run pytest -m live tests/live
```

## Fixed decisions (do not re-litigate)

- Tool prefix `neon_`; inputs snake_case with NEON's camelCase accepted as aliases;
  outputs use NEON's camelCase keys; neon-mcp's additions are camelCase too.
- Transports: stdio and stateless Streamable HTTP at `/mcp` (+ `/healthz`, `/readyz`);
  no SSE, no sessions, no OIDC, no roots/sampling/logging.
- Config: `NEON_MCP_<SECTION>__<FIELD>`; precedence flag > env > YAML > defaults;
  token `NEON_MCP_NEON__API_TOKEN`, fallbacks `NEON_TOKEN`, `NEON_API_TOKEN`; no token flag.
- Downloads exist only on stdio, confined to `downloads.directory`.
- MIT, Copyright (c) 2026 The Regents of the University of New Mexico.

## NEON facts that drive the code

- Since API 0.11.0 (June 2026) `/data/*`, `/data/query`, `/releases/{tag}/data/*`,
  `/samples/view` and `/samples/download` return 403 without `X-API-Token`; all else is
  anonymous. Rate limits: 200 burst / 2 rps anonymous (per IP), 2000 / 8 rps with a token.
- Unknown codes are HTTP **400** "… not found" (→ `not_found`), not 404.
- `PROVISIONAL` is not a release; `?release=PROVISIONAL` is a 400. Use the
  `provisional` / `include_provisional` switches.
- GraphQL lives at `https://data.neonscience.org/graphql` (not `/api/v0`). Catalogs come
  from GraphQL (3.6 MB products, 0.6 MB sites) instead of the 30 MB / 27 MB REST lists;
  `filterProducts`/`filterSites` window `availableMonths` but not `availableReleases`.
- `/releases/{tag}/products|sites` (22–26 MB) are never called.

## Code map

`server.py` is the only SDK-coupled module (adapter); `registry.py` validates, enforces
token fail-fast and the result budget; tools in `tools/<family>.py` are
`async (args, ctx) -> OutputModel`; projections in `projections/`; NEON access in
`neon/` (client, rate limiter, cache, catalog, resolve, filenames, downloads);
transports in `transport/`. See `docs/develop/architecture.md`.

## Adding a tool

Models (`NeonInput` / `ToolResultBase`, every input field described) → `@register_tool`
(name `^neon_[a-z_]+$`, description ≤ 600 chars ending in a `Next:` sentence, honest
annotations, every NEON endpoint listed, `requires_token` for token-only endpoints) →
import in `tools/__init__.py` → fixture + route in `tests/fixture_router.py` → tests via
`tests.helpers.call_ok` (validates `outputSchema`) → a live test in `tests/live/` →
`python scripts/gen_tools_reference.py`.

## Testing rules

- Unit tests never touch the network; the FixtureRouter fails on unrouted requests.
- Fixtures are real responses, shrunk and scrubbed (`python scripts/record_fixtures.py check`).
- Live tests are marked `live` and run only with `NEON_MCP_LIVE=1`.

## Security rules

- A token is sent only as `X-API-Token`, only to NEON hosts, never logged, cached in
  clear, echoed, or placed in MRTR `requestState`.
- Over HTTP, header tokens need `https://` `public_base_url`; the operator token is not
  shared unless `share_config_token_over_http`.
- Downloads: real-path confinement, basename allow-list, host allow-list on every hop,
  caps checked before transfer, `.part` + MD5.

## Docs follow OKF v0.2

`docs/` is an Open Knowledge Format v0.2 bundle rendered with Zensical. Every content
page has frontmatter (`type`, `title`, `description`, `tags`, `generated`, `sources`,
optional `status`/`stale_after`); section `index.md` files have none; `docs/log.md` gets
a dated entry per change; never add `verified:`. After changes run
`gen_tools_reference.py`, `gen_config_reference.py`, `gen_llms_txt.py` and
`okf_validate.py docs`. Full rules: `AGENTS.md`.

## Releases

Version in `src/neon_mcp/__init__.py`; `CHANGELOG.md` (Keep a Changelog) for the
package, `docs/log.md` for the docs; tag `vX.Y.Z` to publish via `release.yml`.
