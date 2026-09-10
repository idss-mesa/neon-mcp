---
title: "Taxonomy"
description: "Page through NEON's taxon lists with neon_search_taxonomy by type code or rank, with exact scientific names, a genus fallback and Darwin Core keys."
type: Guide
tags:
  - tools
  - taxonomy
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-taxonomy
    resource: "https://data.neonscience.org/data-api/endpoints/taxonomy/"
    title: "NEON Data API — Taxonomy endpoint"
    author: "team:neon"
status: stable
---

# Taxonomy

[`neon_search_taxonomy`](reference.md#neon_search_taxonomy) pages through NEON's
taxonomy lists — the names NEON field staff use for birds, beetles, plants, small
mammals, ticks and other groups[^neon-taxonomy].

* Either a `taxon_type_code` (`ALGAE`, `BEETLE`, `BIRD`, `FISH`, `HERPETOLOGY`,
  `MACROINVERTEBRATE`, `MOSQUITO`, `MOSQUITO_PATHOGENS`, `PLANT`, `SMALL_MAMMAL`,
  `TICK`) **or** rank filters (`kingdom`, `phylum`, `division`, `class`, `order`,
  `family`, `genus`, `scientific_name`) — NEON rejects both together, and neon-mcp
  refuses the combination before calling.
* `scientific_name` must match exactly upstream; if an exact `"Genus species"` finds
  nothing, neon-mcp retries by genus and keeps names starting with your text
  (`fuzzyFallbackUsed: true`).
* Rows keep NEON's Darwin Core keys verbatim (`dwc:scientificName`,
  `dwc:vernacularName`, `dwc:family`, …). `verbose=true` adds every rank and extra
  field, drops null ones, and caps `limit` at 100.
* Paging follows NEON's own `next` link: continue with `offset=page.nextOffset`.

```json
{"taxon_type_code": "BIRD", "limit": 25}
```

[^neon-taxonomy]: NEON Data API — Taxonomy endpoint. <https://data.neonscience.org/data-api/endpoints/taxonomy/>
