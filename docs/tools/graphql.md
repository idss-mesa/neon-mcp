---
title: "GraphQL"
description: "Use neon_graphql, a guard-railed read-only GraphQL tool, for NEON metadata shapes the dedicated tools do not cover, and its introspection mode."
type: Guide
tags:
  - tools
  - graphql
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-graphql
    resource: "https://data.neonscience.org/data-api/graphql/"
    title: "NEON Data API — GraphQL"
    author: "team:neon"
status: stable
---

# GraphQL

NEON serves a public GraphQL endpoint at `https://data.neonscience.org/graphql`
(not under `/api/v0`) for product, site, location and prototype metadata[^neon-graphql].
[`neon_graphql`](reference.md#neon_graphql) runs your own query there when the
dedicated tools do not produce the shape you need.

```json
{"query": "{ filterSites(filter: {siteCodes: [\"HARV\"], productCodes: [\"DP1.10003.001\"]}) { siteCode dataProducts { dataProductCode availableMonths } } }"}
```

Guard rails, all checked before the request:

* read-only: `query` operations only (no mutations or subscriptions);
* allowed roots: `products`, `product`, `demoProduct`, `filterProducts`, `sites`, `site`,
  `filterSites`, `location`, `locationHierarchy`, `findLocations`,
  `prototypeDatasets`, `prototypeDataset`, and one `__type` or `__schema` (NEON rejects
  more as `BadFaithIntrospection`);
* at most 8000 characters and a selection depth of 8;
* no NEON token is ever sent; results are never cached.

Responses larger than `max_bytes` (50 KB by default, up to 200 KB) have their largest
lists shortened; `truncatedPaths` says where. `introspect_type="Site"` describes one
type. The `neon://reference/graphql-schema` resource summarises the schema, including
the `availableReleases` windowing caveat and the fields GraphQL lacks.

[^neon-graphql]: NEON Data API — GraphQL. <https://data.neonscience.org/data-api/graphql/>
