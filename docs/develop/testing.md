---
title: "Testing"
description: "The neon-mcp test layout: hermetic fixtures and the FixtureRouter, the conformance suite, live tests, coverage and the CI jobs."
type: Reference
tags:
  - develop
  - testing
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: tests
    resource: "https://github.com/idss-mesa/neon-mcp/tree/main/tests"
    title: "neon-mcp tests"
    author: "team:idss-mesa"
status: stable
---

# Testing

```bash
uv run pytest                      # unit + conformance, no network (about 350 tests, a few seconds)
uv run pytest --cov=neon_mcp       # with coverage (95 % at 0.1.0)
NEON_MCP_LIVE=1 uv run --env-file .env pytest -m live tests/live   # against the real API
```

Live tests that need a token skip unless `NEON_TOKEN` is set. Keep it in the
git-ignored `.env` (`NEON_TOKEN=...`) and load it with `uv run --env-file .env`, since
neither pytest nor neon-mcp reads `.env` on its own. Don't put the token on the command
line, where it lands in shell history.

## Hermetic by default

Unit tests never touch the network. `tests/fixture_router.py` is an
`httpx.MockTransport` handler over `tests/fixtures/` (real NEON responses recorded on
2026-09-10, shrunk and scrubbed; see `tests/fixtures/MANIFEST.md`). It replays NEON's
rate-limit headers, answers token endpoints with NEON's real 403 when `X-API-Token` is
missing, records every call (tests assert call counts, cache hits and that tokens never
reach storage hosts) and fails the test on any unrouted request. Sleeps and clocks are
injected, so retries and rate limits run instantly.

## Layout

| Path | Covers |
| --- | --- |
| `tests/test_*.py` | config, errors, redaction, registry and budget, adapter, CLI, resources, prompts, conformance |
| `tests/neon/` | client, rate limiter, cache, auth, months, catalog, resolution, GraphQL guard, file names, download manager |
| `tests/tools/` | every tool family through `call_ok` / `call_err` (results validated against `outputSchema`) |
| `tests/transport/` | Streamable HTTP app, health checks, token passthrough, a real stdio subprocess in both protocol eras |

## CI

`.github/workflows/ci.yml` runs ruff, `mypy --strict`, pytest with coverage and the
fixture scrub check on Python 3.11–3.13, a macOS subset, a separate MCP 2026-07-28
conformance job (SDK major version, deprecated-feature grep), and nightly live tests.
`.github/workflows/docs.yml` validates the OKF bundle, checks that generated docs are
current, builds the site and deploys it.
