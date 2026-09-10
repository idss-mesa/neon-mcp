---
title: "Sites"
description: "Find NEON's field sites with neon_search_sites by name, state, domain, type, product or proximity, and read one site with neon_get_site."
type: Guide
tags:
  - tools
  - sites
  - catalog
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-sites
    resource: "https://data.neonscience.org/data-api/endpoints/sites/"
    title: "NEON Data API — Sites endpoint"
    author: "team:neon"
  - id: neon-field-sites
    resource: "https://www.neonscience.org/field-sites/explore-field-sites"
    title: "NEON — Explore field sites"
    author: "team:neon"
status: stable
---

# Sites

NEON operates 81 field sites (terrestrial and aquatic, `CORE` and `GRADIENT`) in 20
ecoclimatic domains `D01`–`D20`[^neon-field-sites]. Sites have four-letter codes
(`HARV` is Harvard Forest). Tools:
[`neon_search_sites`](reference.md#neon_search_sites) and
[`neon_get_site`](reference.md#neon_get_site).

## Searching

Served from a cached site catalog (about 0.6 MB over GraphQL instead of the 27 MB
REST list). Filters combine:

* `query` — code, name words, state or domain names (`"Harvard"`, `"Alaska"`);
* `domain_code`, `state_code` (two letters), `site_type` (`CORE` or `GRADIENT`);
* `product` — only sites with data for that product (code or name);
* `latitude` + `longitude` (+ `radius_km`, default 100) — nearest first, each result
  with `distanceKm`;
* `include_elevation` — adds elevation and UTM coordinates from one extra cached
  request (`/locations/sites`, 2.7 MB upstream).

## One site

`neon_get_site` accepts a code or a name and returns the site record plus, by
default, every data product available there with its month ranges and the number of
provisional months[^neon-sites]. Other sections: `releases`, `description` (the full
text; summaries are clipped), `location` (elevation, UTM, location properties,
active periods) or `all`. Filter the product list with `products_query` and page it
with `products_offset`.

## Pitfalls

* Some locations of type `SITE` are not field sites (headquarters, mobile
  deployment platforms); `neon_search_sites` covers only the 81 field sites.
* A misspelled or partial name that fits several sites returns `ambiguous_input`;
  similar-looking names do not resolve silently ("Blue Ridge" is not "Blue River").

[^neon-sites]: NEON Data API — Sites endpoint. <https://data.neonscience.org/data-api/endpoints/sites/>
[^neon-field-sites]: NEON — Explore field sites. <https://www.neonscience.org/field-sites/explore-field-sites>
