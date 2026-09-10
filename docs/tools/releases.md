---
title: "Releases and citations"
description: "Browse NEON's annual data releases and their DOIs with neon_list_releases and neon_get_release, and cite data correctly with neon_get_citation."
type: Guide
tags:
  - tools
  - releases
  - citation
  - DOI
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-releases
    resource: "https://data.neonscience.org/data-api/endpoints/releases/"
    title: "NEON Data API — Releases endpoint"
    author: "team:neon"
  - id: neon-citation
    resource: "https://www.neonscience.org/data-samples/data-policies-citation"
    title: "NEON — Data Policies and Citation Guidelines"
    author: "team:neon"
status: stable
stale_after: "2027-02-01T00:00:00Z"
---

# Releases and citations

Every January NEON publishes an immutable **release** with a DOI for each data
product; six exist as of September 2026 (`RELEASE-2021` … `RELEASE-2026`)[^neon-releases].
Tools: [`neon_list_releases`](reference.md#neon_list_releases),
[`neon_get_release`](reference.md#neon_get_release) and
[`neon_get_citation`](reference.md#neon_get_citation).

## Releases

`neon_list_releases` returns every release newest first with its generation date,
product count and manifest artifacts (signed manifest URLs only with
`include_artifact_urls`). `neon_get_release` takes a tag, a release UUID or
`latest` and returns its products with DOIs (paged, filterable with `product_query`);
`include` adds `sites` (codes and names) and `artifacts`. `product_code` or `site_code`
return that product or site exactly as published in the release.

An unknown tag fails with `not_found` and `validReleases`.

!!! note "Why the release site and product lists are never fetched"

    NEON's `/releases/{tag}/sites` and `/releases/{tag}/products` return 22 MB and
    26 MB. neon-mcp builds the release site list from a codes-only GraphQL query
    instead and never calls those endpoints.

## Citations

`neon_get_citation` renders NEON's recommended wording[^neon-citation] with the DOI of
the newest release that has one (or the `release` you name), plus a BibTeX entry:

```text
NEON (National Ecological Observatory Network). Breeding landbird point counts (DP1.10003.001), RELEASE-2026. https://doi.org/10.48443/v6hs-mx57. Dataset accessed from https://data.neonscience.org on September 10, 2026.
```

* `provisional=true` produces the provisional form (no DOI; archive what you used).
* `prototype_uuid` cites a prototype dataset by its own DOI and version.
* The DOI is cross-checked against the release record; a mismatch is reported in
  `notes`.
* The templates live in the `neon://guide/citing-neon-data` resource and
  [Citing NEON data](../about/citing-neon.md).

[^neon-releases]: NEON Data API — Releases endpoint. <https://data.neonscience.org/data-api/endpoints/releases/>
[^neon-citation]: NEON — Data Policies and Citation Guidelines. <https://www.neonscience.org/data-samples/data-policies-citation>
