# Test fixtures

Recorded from the live NEON Data API on 2026-09-10 and shrunk (at most 3 sites,
6 months and 5 list items; every top-level key kept). Signed-URL signatures are
replaced with `REDACTED`. `python scripts/record_fixtures.py check` enforces the
rules; `tests/fixture_router.py` maps every served fixture to a route.

Hand-written or derived (not recorded verbatim):

| Fixture | Origin |
|---|---|
| `graphql_products_catalog.json`, `graphql_sites_catalog.json` | derived from `products.json` / `sites.json` by `scripts/record_fixtures.py derive-gql-catalog` (the exact GraphQL selections neon-mcp sends; parity with the REST build is a unit test) |
| `data_DP1.00001.001_ABBY_2023-01.json`, `dataquery_DP1.00001.001_ABBY.json`, `samples_view_barcode.json`, `samples_classes_ok.json` | hand-written in the documented response shapes (token-only endpoints) |
| `release_400_not_found.json` | NEON's 400 body for an unknown release (shape verified live) |
| `taxonomy_TICK_ping.json` | the `neon_ping(check_api=true)` probe response |
| `rate_limited_429.headers`, `error_500.txt` | retry/backoff paths |
| `release_RELEASE-2025_products.json`, `release_RELEASE-2025_sites.json` | payload-hazard samples; **no route serves them** (neon-mcp never calls these endpoints) |
