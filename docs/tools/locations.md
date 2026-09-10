---
title: "Locations"
description: "Walk NEON location hierarchies by type with neon_find_locations (towers, plots, huts) and read one location in depth with neon_get_location."
type: Guide
tags:
  - tools
  - locations
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-locations
    resource: "https://data.neonscience.org/data-api/endpoints/locations/"
    title: "NEON Data API — Locations endpoint"
    author: "team:neon"
status: stable
stale_after: "2027-09-10T00:00:00Z"
---

# Locations

Every NEON measurement is tied to a named location in a tree: `REALM` → domain
(`D01`) → site (`HARV`) → towers, huts, soil arrays, observation plots and the
sensor positions under them[^neon-locations]. Tools:
[`neon_find_locations`](reference.md#neon_find_locations) and
[`neon_get_location`](reference.md#neon_get_location).

## Finding locations of a type

Give a `root` (`REALM`, a domain, a site or any location) or up to 20 `site_codes`,
and usually a `location_type`. NEON prunes the hierarchy to that type, which keeps the
walk small: Harvard Forest's full hierarchy is 1.2 MB with 595 top-level children,
its `TOWER` walk about 12 KB.

```json
{"site_codes": ["HARV"], "location_type": "TOWER"}
```

* Under `REALM` or a domain, `location_type` is **required** (the unfiltered tree is
  enormous). `REALM` + `SITE` and `REALM` + `DOMAIN` use fast paths.
* A site walk without `location_type` returns `typesAvailable` (counts per type seen
  in that one fetch) so you can narrow the next call.
* Common types: `TOWER`, `LEVEL`, `BOOM`, `HUT`, `MEGAPIT`, `SOIL_PLOT`,
  `SOIL_ARRAY`, `CONFIG`, and observation plots such as `OS Plot - mam` (small
  mammals) or `OS Plot - brd` (birds). The full observed list is in
  `neon://reference/vocabularies`; matching is case-insensitive.
* `include_coordinates` (default on) looks up coordinates for the returned page in
  one batched GraphQL call; `latitude`/`longitude`/`radius_km` filter by distance.

## One location

`neon_get_location` returns coordinates, UTM, elevation, orientation and offsets,
active periods and (by default) properties folded into a name → value object.
Optional: `hierarchy` (parent chain up to `REALM`), `children` (paged; prune with
`location_type`), `history` (up to 100 past positions), `polygon`.

## Pitfalls

* Location names are case-sensitive (`HARV_001.basePlot.bet`); four-letter site codes
  and domains are upper-cased for you.
* Unknown names come back from NEON as HTTP 400 "Location not found", reported as
  `not_found`.

[^neon-locations]: NEON Data API — Locations endpoint. <https://data.neonscience.org/data-api/endpoints/locations/>
