---
title: "Products"
description: "Find NEON data products with neon_search_products and read one in depth with neon_get_product, including its opt-in detail sections."
type: Guide
tags:
  - tools
  - products
  - catalog
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-products
    resource: "https://data.neonscience.org/data-api/endpoints/products/"
    title: "NEON Data API — Products endpoint"
    author: "team:neon"
  - id: neon-graphql
    resource: "https://data.neonscience.org/data-api/graphql/"
    title: "NEON Data API — GraphQL"
    author: "team:neon"
status: stable
---

# Products

NEON publishes about 200 data products, each identified by a code such as
`DP1.10003.001` (level 1, product 10003, revision 001). Two tools cover them:
[`neon_search_products`](reference.md#neon_search_products) and
[`neon_get_product`](reference.md#neon_get_product).

## Searching

The full REST product list is about 30 MB, so neon-mcp never sends it to an agent.
It fetches a compact projection once over GraphQL (about 3.6 MB, cached for an
hour, rebuilt from REST if GraphQL fails) and searches it locally[^neon-graphql].

* `query` — every word must match a name, keyword, theme or description (small
  typos are tolerated); a bare code such as `DP1.10003` matches exactly.
* `theme` (prefix: `atmo`, `organisms`, ...), `science_team` (`TIS`, `TOS`, `AIS`,
  `AOS`, `AOP`), `level` (1–4), `has_expanded`, `status` (`ACTIVE` by default;
  `FUTURE`, `RETIRED` or `ALL`).
* `site` or `domain_code` — only products with data there; `available_from` /
  `available_to` — only products whose months overlap the range.

```json
{"query": "breeding bird point counts"}
```

Each hit carries its score, what matched (`matchedOn`), site count, overall month
range and latest release; `facets` count themes, teams, levels and statuses over the
whole filtered set, and `didYouMean` suggests terms when nothing matches.

## One product in depth

`neon_get_product` accepts a code or a name (`"breeding landbird"` resolves to
`DP1.10003.001` and is echoed in `resolved`). With no `include`, it answers from the
cached catalog without another request: codes, team, themes, keywords, releases with
DOIs and an availability summary.

Opt-in sections come from the REST detail record[^neon-products]:

| `include` | Adds |
| --- | --- |
| `abstract`, `design`, `study`, `sensor`, `remarks`, `packages` | text, clipped to `text_budget` (4000 characters by default; clipped fields are listed in `textTruncated`) |
| `specs` | the product's documents (ATBDs, protocols, user guides) with spec numbers and URLs |
| `change_logs` | issue log entries, newest first, paged by `change_logs_offset` / `change_logs_limit` |
| `availability` | one row per site with month ranges per release (see [Availability](availability-and-data.md)) |
| `biorepository` | biorepository collections holding physical samples |
| `all` | everything above |

Pass `release` to see the product exactly as published in one release.

## Pitfalls

* Unknown codes: NEON answers HTTP 400 "Product code not found", which neon-mcp
  reports as `not_found`.
* `FUTURE` products have no data yet and are hidden by the default status filter.
* A name that fits several products (`"wind"`) returns `ambiguous_input` with
  candidates; retry with a code.

[^neon-products]: NEON Data API — Products endpoint. <https://data.neonscience.org/data-api/endpoints/products/>
[^neon-graphql]: NEON Data API — GraphQL. <https://data.neonscience.org/data-api/graphql/>
