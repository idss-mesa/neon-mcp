---
title: "Prototype datasets"
description: "Search NEON's prototype datasets with neon_search_prototype_datasets and read one with its files, DOI and descriptions using neon_get_prototype_dataset."
type: Guide
tags:
  - tools
  - prototype-datasets
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-prototype
    resource: "https://data.neonscience.org/data-api/endpoints/prototype/"
    title: "NEON Data API — Prototype datasets"
    author: "team:neon"
status: stable
---

# Prototype datasets

Prototype datasets are early, experimental or one-off NEON data outside the standard
product catalogue, each with its own DOI and version[^neon-prototype]. Tools:
[`neon_search_prototype_datasets`](reference.md#neon_search_prototype_datasets) and
[`neon_get_prototype_dataset`](reference.md#neon_get_prototype_dataset). Neither
needs a token.

* Search by `query` (title, abstract, descriptions, keywords), `theme`, `science_team`,
  `site_code`, `start_year`/`end_year` (overlap), `file_type` or `is_published`;
  `facets` show the exact upstream theme, team and file-type strings.
* Theme and team strings differ from the product catalogue (`Land Cover and
  Processes`, `Aquatic Observational Systems (AOS)`): `theme` matches a prefix and
  `science_team` a substring, so `land cover` and `AOS` both work.
* `neon_get_prototype_dataset` returns the dataset with its files (sizes, MD5s,
  signed URLs that expire in about 7 days) and locations by default; add
  `descriptions`, `citations` and `related`, or `all`.
* Download the files on stdio with `neon_download_files(prototype_uuid=...)`; cite
  with `neon_get_citation(prototype_uuid=...)`.

[^neon-prototype]: NEON Data API — Prototype datasets. <https://data.neonscience.org/data-api/endpoints/prototype/>
