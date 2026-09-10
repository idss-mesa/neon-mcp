---
title: "Availability and data files"
description: "Check which sites and months have NEON data without a token, list data files with signed URLs using a token, and download them on stdio."
type: Guide
tags:
  - tools
  - availability
  - data
  - downloads
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-data
    resource: "https://data.neonscience.org/data-api/endpoints/data/"
    title: "NEON Data API — Data endpoint"
    author: "team:neon"
  - id: neon-data-query
    resource: "https://data.neonscience.org/data-api/endpoints/data-query/"
    title: "NEON Data API — Data query endpoint"
    author: "team:neon"
  - id: neon-auth
    resource: "https://data.neonscience.org/data-api/authentication/"
    title: "NEON Data API — Authentication"
    author: "team:neon"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# Availability and data files

Three tools take you from "does data exist?" to files on disk:
[`neon_get_availability`](reference.md#neon_get_availability) (no token),
[`neon_list_files`](reference.md#neon_list_files) (token) and
[`neon_download_files`](reference.md#neon_download_files) (token for data files; stdio
only).

## Availability (no token)

```json
{"product": "DP1.10003.001", "domain_code": "D01"}
```

* **Product mode** (`product` only): one row per site. **Site mode** (`site` only): one
  row per product. **Cell mode** (both): one row, months listed explicitly by default.
* Months are compressed to ISO-8601 intervals: `["2016-06/2025-06"]`; `format` can be
  `ranges` (default), `months` or `counts`.
* `byRelease` splits every row by release, with `PROVISIONAL` as its own key, and
  `summary` totals site-months per release.
* `start_month` / `end_month` window the result. NEON's GraphQL filter windows
  `availableMonths` but not the per-release lists, so neon-mcp clips those locally
  (a note says so).
* Filters: `site_codes` or `domain_code` (product mode), `product_codes` (site mode),
  `release`, and `provisional` = `include` (default), `exclude` or `only`.

### PROVISIONAL is not a release

Newer data are *provisional*: available but not yet in an annual release, and they may
change. `release="PROVISIONAL"` is rejected (NEON rejects it too); use the
`provisional` switch here and `include_provisional` when listing or downloading files.
Defaults include provisional data everywhere, so what availability shows is what
listing returns.

## Listing files (token)

Since June 2026 NEON's data endpoints require an API token[^neon-auth]; without one
the tool fails with `auth_required` before any request
([set one up](../getting-started/api-token.md)).

```json
{"product": "DP1.10003.001", "site_codes": ["HARV"], "start_month": "2023-06", "kind": "data"}
```

* One site and one month uses `GET /data/{product}/{site}/{month}` (which also returns
  package ZIP links); anything wider uses `POST /data/query`[^neon-data-query].
* Each file carries its name, `kind` (`data`, `variables`, `readme`,
  `sensor_positions`, `eml`, `science_review_flags`, `categorical_codes`,
  `validation`, `package`, `other`), `table`, `hor`/`ver`/`tmi` indices, size, MD5,
  release and a signed URL. Filter with `kind`, `table`, `hor`, `ver`, `tmi`,
  `name_contains` (see `neon://guide/product-code-anatomy` for the file-name grammar).
* Signed URLs expire about 7 days after generation (`urlExpiresAt`); they need no
  token. List again to refresh them, and never cite them.
* `detail="summary"` or `"site_months"` sizes a request without listing files;
  `include_urls=false` shrinks the result. Under the 50 KB result budget, URLs are
  dropped from the end of the page before files are.
* A request may span at most 500 site-months (30 sites × 16 months, for example);
  wider requests fail with `query_too_large` before calling NEON.
* `filename` returns the signed URL of one exact file for a single site-month.

## Downloading (stdio)

`neon_download_files` takes the same selectors, or `prototype_uuid` (+ `file_names`),
or `spec_number` for a NEON document. It exists only on stdio: the files land on the
machine running the server, under `downloads.directory` (`~/neon-downloads`):

```text
~/neon-downloads/DP1.10003.001/HARV/2023-06/NEON.D01.HARV.DP1.10003.001.brd_countdata.2023-06.basic.….csv
~/neon-downloads/prototype/<uuid>/<file>
~/neon-downloads/documents/NEON.DOC.014041vL.pdf
```

Safety rules: the whole plan is checked against 50 files and 2 GiB per call (1 GiB per
file) *before* anything transfers; every destination must resolve inside the download
directory (no `..`, no symlink escapes, plain file names); every URL and redirect must
be on the host allow-list (`data.neonscience.org`, `storage.googleapis.com` and its
subdomains); files stream to `.part` and are renamed only after the MD5 matches.
Existing identical files are skipped (`if_exists="error"` refuses instead);
`as_zip=true` fetches NEON's package ZIP per site-month.

[^neon-data]: NEON Data API — Data endpoint. <https://data.neonscience.org/data-api/endpoints/data/>
[^neon-data-query]: NEON Data API — Data query endpoint. <https://data.neonscience.org/data-api/endpoints/data-query/>
[^neon-auth]: NEON Data API — Authentication. <https://data.neonscience.org/data-api/authentication/>
