---
title: "Tool reference"
description: "Every neon-mcp tool with its inputs, result fields, NEON endpoints, token requirement and annotations, generated from the registry."
type: MCP Tool Reference
tags:
  - tools
  - reference
  - generated
generated:
  by: "process:gen_tools_reference"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: registry
    resource: "https://github.com/idss-mesa/neon-mcp/tree/main/src/neon_mcp/tools"
    title: "neon-mcp tool registry"
    author: "team:idss-mesa"
  - id: neon-api
    resource: "https://data.neonscience.org/data-api/"
    title: "NEON Data API"
    author: "team:neon"
status: stable
---

# Tool reference

Generated from the tool registry by `scripts/gen_tools_reference.py`; do not edit by hand. 20 tools are registered; `neon_download_files` is offered only over stdio, so HTTP deployments list one fewer. Inputs are snake_case; NEON's camelCase spellings (`productCode`, `startDateMonth`) are accepted too. Every result also carries `resolved`, `notes`, `nextSteps` and `source`, and failures return `structuredContent.error` with a stable `code` (see [Utilities](utilities.md#error-codes)).

| Tool | Title | Family | Token |
| --- | --- | --- | --- |
| [`neon_download_files`](#neon_download_files) | Download NEON files | [data](availability-and-data.md) | required |
| [`neon_find_locations`](#neon_find_locations) | Find NEON locations | [locations](locations.md) | no |
| [`neon_get_availability`](#neon_get_availability) | Get NEON data availability | [catalog](products.md) | no |
| [`neon_get_citation`](#neon_get_citation) | Cite NEON data | [releases](releases.md) | no |
| [`neon_get_document`](#neon_get_document) | Get a NEON document | [documents](utilities.md) | no |
| [`neon_get_location`](#neon_get_location) | Get a NEON location | [locations](locations.md) | no |
| [`neon_get_product`](#neon_get_product) | Get a NEON data product | [catalog](products.md) | no |
| [`neon_get_prototype_dataset`](#neon_get_prototype_dataset) | Get a NEON prototype dataset | [prototype](prototype-datasets.md) | no |
| [`neon_get_release`](#neon_get_release) | Get a NEON data release | [releases](releases.md) | no |
| [`neon_get_sample`](#neon_get_sample) | Get a NEON sample | [samples](samples.md) | required |
| [`neon_get_site`](#neon_get_site) | Get a NEON field site | [catalog](products.md) | no |
| [`neon_graphql`](#neon_graphql) | Run a NEON GraphQL query | [graphql](graphql.md) | no |
| [`neon_list_files`](#neon_list_files) | List NEON data files | [data](availability-and-data.md) | required |
| [`neon_list_releases`](#neon_list_releases) | List NEON data releases | [releases](releases.md) | no |
| [`neon_list_sample_classes`](#neon_list_sample_classes) | List NEON sample classes | [samples](samples.md) | no |
| [`neon_ping`](#neon_ping) | Check neon-mcp status | [core](utilities.md) | no |
| [`neon_search_products`](#neon_search_products) | Search NEON data products | [catalog](products.md) | no |
| [`neon_search_prototype_datasets`](#neon_search_prototype_datasets) | Search NEON prototype datasets | [prototype](prototype-datasets.md) | no |
| [`neon_search_sites`](#neon_search_sites) | Search NEON field sites | [catalog](products.md) | no |
| [`neon_search_taxonomy`](#neon_search_taxonomy) | Search NEON taxonomy | [taxonomy](taxonomy.md) | no |

## neon_download_files

**Download NEON files.** Download data files (or package ZIPs), a prototype dataset's files, or a NEON document into the configured download directory (stdio only; data files need a token). The plan is checked against file/byte caps before any transfer; MD5s are verified; identical existing files are skipped. Next: read the CSVs (pandas.read_csv) and cite with neon_get_citation.

| | |
| --- | --- |
| Surface | `data` |
| NEON API token | required for NEON data files; prototype and document downloads need none |
| Transports | stdio |
| Annotations | readOnly=false, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /data/package/{productCode}/{siteCode}/{yearMonth}`<br>`GET /prototype/data/{uuid}`<br>`GET /documents/{specNumber}`<br>`POST /data/query` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `product` | string \\| null |  | null | Product code or name. |
| `site_codes` | array of string \\| null |  | null | Site codes or names (up to 30). (min items 1) |
| `start_month` | string \\| null |  | null | First month (YYYY-MM). |
| `end_month` | string \\| null |  | null | Last month (YYYY-MM); defaults to start_month. |
| `package` | `basic` \\| `expanded` |  | `"basic"` | basic (default) or expanded. |
| `release` | string \\| null |  | null | Only files in this release (default: latest per month). |
| `include_provisional` | boolean |  | true | Include PROVISIONAL (unreleased) months. |
| `kind` | `data` \\| `variables` \\| `readme` \\| `sensor_positions` \\| `eml` \\| `science_review_flags` \\| `categorical_codes` \\| `validation` \\| `package` \\| `other` \\| null |  | null | data, variables, readme, sensor_positions, eml, ... or package. |
| `table` | string \\| null |  | null | Table name, e.g. 2DWSD_30min or brd_countdata. |
| `hor` | string \\| null |  | null | Horizontal index, e.g. 000. |
| `ver` | string \\| null |  | null | Vertical index, e.g. 010. |
| `tmi` | string \\| null |  | null | Temporal index in minutes, e.g. 030. |
| `name_contains` | string \\| null |  | null | Substring the file name must contain. |
| `as_zip` | boolean |  | false | Download NEON's package ZIP per site-month instead of files. |
| `prototype_uuid` | string \\| null |  | null | Download a prototype dataset's files instead. |
| `file_names` | array of string \\| null |  | null | With prototype_uuid: only these file names. |
| `spec_number` | string \\| null |  | null | Download one NEON document (e.g. NEON.DOC.000780vD). |
| `dest_subdir` | string \\| null |  | null | Relative sub-directory of the download directory. |
| `if_exists` | `skip` \\| `error` |  | `"skip"` | skip identical existing files (default) or error. |
| `max_bytes` | integer \\| null |  | null | Refuse the plan above this many bytes. (>= 1) |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `downloadDir` | string |  |
| `requested` | integer |  |
| `files` | array of DownloadedFileOut |  |
| `totals` | DownloadTotals |  |

## neon_find_locations

**Find NEON locations.** Locations under a site, domain, REALM or named location, filtered by locationType (towers, huts, megapits, soil plots, observation plots, ...) or text, with coordinates and optional proximity. REALM and domain walks need location_type; site walks without it report typesAvailable. Next: call neon_get_location for one location's detail.

| | |
| --- | --- |
| Surface | `locations` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /locations/{locationName}`<br>`GET /locations/sites`<br>`POST /graphql` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `root` | string \\| null |  | null | Walk the hierarchy under REALM, a domain (D01), a site (HARV) or any named location. (min length 1; max length 200) |
| `site_codes` | array of string \\| null |  | null | Walk these sites instead (codes or names, up to 20). (min items 1; max items 20) |
| `location_type` | string \\| null |  | null | Keep only this type: TOWER, HUT, MEGAPIT, SOIL_PLOT, 'OS Plot - mam', ... (see neon://reference/vocabularies). Required under REALM or a domain; prunes the walk upstream. |
| `query` | string \\| null |  | null | Substring filter on name or description. |
| `latitude` | number \\| null |  | null | With longitude: nearest first, within radius_km. (>= -90; <= 90) |
| `longitude` | number \\| null |  | null | >= -180; <= 180 |
| `radius_km` | number |  | `50.0` | > 0; <= 5000 |
| `include_coordinates` | boolean |  | true | Look up coordinates for the returned page (batched). |
| `max_depth` | integer |  | `6` | Deepest hierarchy level to return. (>= 1; <= 12) |
| `limit` | integer |  | `50` | >= 1; <= 200 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `roots` | array of LocationRoot |  |
| `locationType` | string \\| null |  |
| `typesAvailable` | object of integer \\| null |  |
| `hierarchyNodesScanned` | integer |  |
| `items` | array of LocationSummary |  |
| `page` | Page |  |

## neon_get_availability

**Get NEON data availability.** Which sites and months have data for a product (one row per site), which products have data at a site (one row per product), or one product-site cell; month ranges per release including PROVISIONAL, optionally windowed and filtered. Works without a token and is small (GraphQL). Next: call neon_list_files for a product, site and month range.

| | |
| --- | --- |
| Surface | `catalog` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `POST /graphql`<br>`GET /products/{productCode}`<br>`GET /sites/{siteCode}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `product` | string \\| null |  | null | Product code or name. With no site: one row per site. |
| `site` | string \\| null |  | null | Site code or name. With no product: one row per product. |
| `site_codes` | array of string \\| null |  | null | Product mode: only these sites. (max items 81) |
| `domain_code` | string \\| null |  | null | Product mode: only sites in this domain. |
| `product_codes` | array of string \\| null |  | null | Site mode: only these products. (max items 200) |
| `release` | string \\| null |  | null | Only months in this release (RELEASE-YYYY). |
| `provisional` | `include` \\| `exclude` \\| `only` |  | `"include"` | PROVISIONAL months: include (default), exclude, or only (not with release). |
| `start_month` | string \\| null |  | null | Window start (YYYY-MM). |
| `end_month` | string \\| null |  | null | Window end (YYYY-MM). |
| `format` | `ranges` \\| `months` \\| `counts` \\| null |  | null | ranges (default; 'YYYY-MM/YYYY-MM'), months (explicit lists), counts. Cell mode defaults to months. |
| `limit` | integer |  | `100` | >= 1; <= 500 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `mode` | `product` \\| `site` \\| `cell` |  |
| `productCode` | string \\| null |  |
| `productName` | string \\| null |  |
| `siteCode` | string \\| null |  |
| `siteName` | string \\| null |  |
| `release` | string \\| null |  |
| `provisional` | `include` \\| `exclude` \\| `only` |  |
| `window` | Window \\| null |  |
| `format` | `ranges` \\| `months` \\| `counts` |  |
| `summary` | AvailabilityTotals |  |
| `rows` | array of AvailabilityRow |  |
| `page` | Page |  |

## neon_get_citation

**Cite NEON data.** NEON-format citation text and BibTeX for a data product in a release (DOI, default the newest release with a DOI), for provisional data (no DOI; archive what you used), or for a prototype dataset. Wording follows NEON's data policy (CC BY 4.0). Next: include the citation with any results; read neon://guide/citing-neon-data for the rules.

| | |
| --- | --- |
| Surface | `releases` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /releases`<br>`GET /prototype/datasets/{uuid}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `product` | string \\| null |  | null | Product code or name. |
| `prototype_uuid` | string \\| null |  | null | Cite a prototype dataset instead. |
| `release` | string |  | `"latest"` | RELEASE-YYYY, a release uuid, or 'latest' (newest with a DOI). |
| `provisional` | boolean |  | false | Cite provisional data (no DOI). Not with an explicit release. |
| `format` | `text` \\| `bibtex` \\| `all` |  | `"all"` |  |
| `accessed_on` | string \\| null |  | null | Access date for the citation (default: today, UTC). |
| `site_codes` | array of string \\| null |  | null | Sites the data came from (noted). (max items 81) |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `productCode` | string \\| null |  |
| `prototypeUuid` | string \\| null |  |
| `productName` | string \\| null |  |
| `projectTitle` | string \\| null |  |
| `release` | string \\| null |  |
| `provisional` | boolean |  |
| `doi` | string \\| null | Bare DOI, e.g. 10.48443/v6hs-mx57. |
| `doiUrl` | string \\| null |  |
| `accessedOn` | string |  |
| `citationText` | string \\| null |  |
| `bibtex` | string \\| null |  |
| `dataPolicyUrl` | string |  |

## neon_get_document

**Get a NEON document.** Metadata of a NEON document (ATBD, protocol, user guide) by spec number or documents URL: type, size, file name, description and the products that reference it; optionally its text, extracted in memory and paged by character offset. No token. Next: page through text with char_offset, or call neon_download_files(spec_number=...) on stdio.

| | |
| --- | --- |
| Surface | `documents` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /documents/{specNumber}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `spec_number` | string \\| null |  | null | Document number, e.g. NEON.DOC.000780vD. |
| `url` | string \\| null |  | null | A https://data.neonscience.org/api/v0/documents/... URL. |
| `product` | string \\| null |  | null | Check the document belongs to this product (code or name). |
| `extract_text` | boolean |  | false | Extract the text (PDF via pypdf; needs neon-mcp[pdf]). |
| `max_chars` | integer |  | `20000` | >= 500; <= 100000 |
| `char_offset` | integer |  | `0` | >= 0 |
| `pages` | string \\| null |  | null | PDF pages to extract, e.g. '1-5' or '3'. |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `specNumber` | string |  |
| `url` | string |  |
| `contentType` | string \\| null |  |
| `size` | integer \\| null |  |
| `filename` | string \\| null |  |
| `specDescription` | string \\| null |  |
| `specType` | string \\| null |  |
| `referencedByProducts` | array of string |  |
| `text` | string \\| null |  |
| `textTruncated` | boolean |  |
| `nextCharOffset` | integer \\| null |  |
| `charsTotal` | integer \\| null |  |
| `pageCount` | integer \\| null |  |
| `pages` | string \\| null |  |

## neon_get_location

**Get a NEON location.** One named location in depth: coordinates, UTM, elevation, orientation and offsets, properties, active periods; optionally its parent chain, location history, polygon and paged children (pruned by location_type). Names are case-sensitive. Next: call neon_find_locations to list locations of a type under it.

| | |
| --- | --- |
| Surface | `locations` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /locations/{locationName}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `name` | string | yes |  | Location name (case-sensitive), e.g. HARV, TOWER100450, D01. (min length 1; max length 200) |
| `include` | array of `properties` \\| `hierarchy` \\| `history` \\| `children` \\| `polygon` \\| `all` |  |  | properties (default), hierarchy (parent chain), history, children (paged), polygon, all. |
| `location_type` | string \\| null |  | null | Prune children to this type (required for REALM/domains). |
| `children_limit` | integer |  | `50` | >= 1; <= 500 |
| `children_offset` | integer |  | `0` | >= 0 |
| `hierarchy_max_depth` | integer |  | `3` | >= 1; <= 12 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `locationName` | string |  |
| `locationDescription` | string \\| null |  |
| `locationType` | string \\| null |  |
| `domainCode` | string \\| null |  |
| `siteCode` | string \\| null |  |
| `locationDecimalLatitude` | number \\| null |  |
| `locationDecimalLongitude` | number \\| null |  |
| `locationElevation` | number \\| null |  |
| `locationUtmEasting` | number \\| null |  |
| `locationUtmNorthing` | number \\| null |  |
| `locationUtmHemisphere` | string \\| null |  |
| `locationUtmZone` | integer \\| null |  |
| `alphaOrientation` | number \\| null |  |
| `betaOrientation` | number \\| null |  |
| `gammaOrientation` | number \\| null |  |
| `xOffset` | number \\| null |  |
| `yOffset` | number \\| null |  |
| `zOffset` | number \\| null |  |
| `offsetLocation` | object \\| null |  |
| `activePeriods` | array of object |  |
| `hasPolygon` | boolean |  |
| `propertyCount` | integer |  |
| `locationProperties` | object \\| null |  |
| `locationPropertiesRaw` | array of object \\| null |  |
| `locationPolygon` | object \\| null |  |
| `locationParent` | string \\| null |  |
| `locationParentUrl` | string \\| null |  |
| `parentChain` | array of ParentRef \\| null |  |
| `childrenByType` | object of integer \\| null |  |
| `children` | array of LocationSummary \\| null |  |
| `childrenPage` | Page \\| null |  |
| `hierarchyNodesScanned` | integer \\| null |  |
| `locationHistory` | array of HistoryEntry \\| null |  |
| `historyTruncated` | boolean |  |

## neon_get_product

**Get a NEON data product.** One data product: codes, name, team, status, themes, keywords, releases with DOIs and an availability summary; opt-in include[] sections add abstract and design text, packages, specs (ATBDs, protocols), change logs (paged), per-site availability rows and biorepository collections. Accepts a code or a name. Next: call neon_get_availability or neon_get_citation for the product.

| | |
| --- | --- |
| Surface | `catalog` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `POST /graphql`<br>`GET /products/{productCode}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `product` | string | yes |  | Product code (DP1.10003.001, DP1.10003) or name ('breeding landbird'). |
| `release` | string \\| null |  | null | The product as published in one release. |
| `include` | array of `abstract` \\| `design` \\| `study` \\| `sensor` \\| `remarks` \\| `packages` \\| `specs` \\| `releases` \\| `change_logs` \\| `availability` \\| `biorepository` \\| `all` |  |  | Opt-in sections: abstract, design, study, sensor, remarks, packages, specs, releases, change_logs, availability, biorepository, or all. Empty = compact base record. |
| `change_logs_limit` | integer |  | `25` | >= 1; <= 200 |
| `change_logs_offset` | integer |  | `0` | >= 0 |
| `availability_limit` | integer |  | `100` | >= 1; <= 300 |
| `availability_offset` | integer |  | `0` | >= 0 |
| `text_budget` | integer |  | `4000` | Characters kept per text section. (>= 100; <= 20000) |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `productCode` | string |  |
| `productCodeLong` | string |  |
| `productCodePresentation` | string |  |
| `productName` | string |  |
| `productDescription` | string \\| null |  |
| `productStatus` | string |  |
| `productCategory` | string |  |
| `productScienceTeam` | string \\| null |  |
| `productScienceTeamAbbr` | string \\| null |  |
| `productPublicationFormatType` | string \\| null |  |
| `productHasExpanded` | boolean |  |
| `themes` | array of string |  |
| `keywords` | array of string |  |
| `latestRelease` | string \\| null |  |
| `releases` | array of ReleaseInfo |  |
| `availability` | AvailabilitySummary |  |
| `specsCount` | integer |  |
| `changeLogCount` | integer \\| null | Absent when served from the catalog (no change logs there). |
| `urls` | ProductUrls |  |
| `productAbstract` | string \\| null |  |
| `productDesignDescription` | string \\| null |  |
| `productStudyDescription` | string \\| null |  |
| `productSensor` | string \\| null |  |
| `productRemarks` | string \\| null |  |
| `productBasicDescription` | string \\| null |  |
| `productExpandedDescription` | string \\| null |  |
| `textTruncated` | array of string | Text fields clipped to text_budget. |
| `specs` | array of SpecInfo \\| null |  |
| `changeLogs` | array of ChangeLog \\| null |  |
| `changeLogsPage` | Page \\| null |  |
| `availabilityRows` | array of AvailabilityRow \\| null |  |
| `availabilityPage` | Page \\| null |  |
| `biorepositoryCollections` | array of BiorepositoryCollection \\| null |  |

## neon_get_prototype_dataset

**Get a NEON prototype dataset.** One prototype dataset: title, abstract, years, version, DOI, themes, teams, sites, and by default its files with sizes, MD5s and signed URLs; optional project/design/metadata descriptions, publication citations and related products. Next: call neon_download_files(prototype_uuid=...) on stdio, or neon_get_citation(prototype_uuid=...).

| | |
| --- | --- |
| Surface | `prototype` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /prototype/datasets/{uuid}`<br>`GET /prototype/data/{uuid}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `uuid` | string | yes |  | Prototype dataset uuid. |
| `include` | array of `files` \\| `descriptions` \\| `locations` \\| `citations` \\| `related` \\| `all` |  |  | files (default; signed URLs), locations (default), descriptions, citations, related, all. |
| `include_urls` | boolean |  | true | Include signed download URLs (valid ~7 days). |
| `files_limit` | integer |  | `100` | >= 1; <= 500 |
| `files_offset` | integer |  | `0` | >= 0 |
| `text_budget` | integer |  | `4000` | >= 100; <= 20000 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `uuid` | string |  |
| `projectTitle` | string |  |
| `datasetAbstract` | string \\| null |  |
| `abstractTruncated` | boolean |  |
| `startYear` | integer \\| null |  |
| `endYear` | integer \\| null |  |
| `version` | string \\| null |  |
| `isPublished` | boolean \\| null |  |
| `doi` | DoiInfo \\| null |  |
| `dataThemes` | array of string |  |
| `scienceTeams` | array of string |  |
| `siteCodes` | array of string |  |
| `fileTypes` | array of string |  |
| `keywords` | array of string |  |
| `dateUploaded` | string \\| null |  |
| `projectDescription` | string \\| null |  |
| `designDescription` | string \\| null |  |
| `metadataDescription` | string \\| null |  |
| `studyAreaDescription` | string \\| null |  |
| `versionDescription` | string \\| null |  |
| `relatedVersions` | array of object |  |
| `locations` | array of object \\| null |  |
| `publicationCitations` | array of object \\| null |  |
| `relatedDataProducts` | array of object \\| null |  |
| `dataUrl` | string \\| null |  |
| `dataLocations` | array of object |  |
| `files` | array of PrototypeFile \\| null |  |
| `filesPage` | Page \\| null |  |
| `urlsElided` | boolean |  |

## neon_get_release

**Get a NEON data release.** One release (tag, uuid or 'latest'): its data products with DOIs (paged, filterable), optionally its sites and manifest artifacts, or one product/site exactly as published in that release. Unknown tags fail with the list of valid releases. Next: call neon_get_citation for a product in the release.

| | |
| --- | --- |
| Surface | `releases` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /releases/{releaseIdentifier}`<br>`POST /graphql`<br>`GET /releases/{releaseTag}/products/{productCode}`<br>`GET /releases/{releaseTag}/sites/{siteCode}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `release` | string | yes |  | RELEASE-YYYY, a release uuid, or 'latest'. |
| `include` | array of `products` \\| `sites` \\| `artifacts` \\| `all` |  |  | products (default; codes, names, DOIs), sites (codes and names), artifacts (manifests), all. |
| `product_query` | string \\| null |  | null | Filter products by code or name substring. |
| `products_limit` | integer |  | `50` | >= 1; <= 500 |
| `products_offset` | integer |  | `0` | >= 0 |
| `product_code` | string \\| null |  | null | Also return this product as published in the release. |
| `site_code` | string \\| null |  | null | Also return this site as published in the release. |
| `include_artifact_urls` | boolean |  | false | Include signed manifest URLs. |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `release` | string |  |
| `uuid` | string \\| null |  |
| `generationDate` | string \\| null |  |
| `productCount` | integer |  |
| `artifacts` | array of Artifact \\| null |  |
| `dataProducts` | array of ReleaseProduct \\| null |  |
| `productsPage` | Page \\| null |  |
| `sites` | array of ReleaseSite \\| null |  |
| `product` | ProductCore \\| null |  |
| `site` | SiteCore \\| null |  |

## neon_get_sample

**Get a NEON sample.** A physical sample's custody chain (NEON API token required): identifiers, events with their field values, parents and children; degree=N adds relatives N steps away. Identify it by tag (+class), UUID, barcode or archive GUID; an ambiguous tag asks which class (MRTR) or lists candidates. Next: follow parent or child identifiers with another neon_get_sample call.

| | |
| --- | --- |
| Surface | `samples` |
| NEON API token | required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| Multi round-trip | may return `input_required` (elicitation) |
| NEON endpoints | `GET /samples/view`<br>`GET /samples/download`<br>`GET /samples/classes` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `sample_tag` | string \\| null |  | null | Sample tag (use with sample_class when it is ambiguous). |
| `sample_class` | string \\| null |  | null | Sample class of the tag, e.g. bet_IDandpinning_in.individualID. |
| `sample_uuid` | string \\| null |  | null | Sample UUID. |
| `barcode` | string \\| null |  | null | Sample barcode. |
| `archive_guid` | string \\| null |  | null | Biorepository archive GUID. |
| `degree` | integer \\| null |  | null | Also return relatives up to this many degrees away. (>= 1; <= 5) |
| `include_events` | boolean |  | true | Include custody events (field entries folded into objects). |
| `events_limit` | integer |  | `50` | >= 1; <= 500 |
| `fields` | array of string \\| null |  | null | Keep only these smsKey fields in events. |
| `limit` | integer |  | `20` | >= 1; <= 100 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of SampleView |  |
| `degree` | integer \\| null |  |
| `identifier` | object of string |  |
| `page` | Page |  |

## neon_get_site

**Get a NEON field site.** One field site: name, type, state, domain, coordinates, DEIMS id, and (by default) every data product available there with month ranges and provisional counts; optional releases, full description and location record (elevation, UTM, properties). Next: call neon_get_availability or neon_list_files for a product at this site.

| | |
| --- | --- |
| Surface | `catalog` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /sites/{siteCode}`<br>`GET /locations/{locationName}` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `site` | string | yes |  | Site code (HARV) or name ('Harvard Forest'). |
| `release` | string \\| null |  | null | The site as of one release. |
| `include` | array of `products` \\| `releases` \\| `description` \\| `location` \\| `all` |  |  | Sections: products (default; per-product month ranges), releases, description (full text), location (elevation, UTM, properties), all. |
| `products_query` | string \\| null |  | null | Filter products by code or title substring. |
| `products_limit` | integer |  | `100` | >= 1; <= 300 |
| `products_offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `siteCode` | string |  |
| `siteName` | string |  |
| `siteDescription` | string \\| null |  |
| `siteType` | string |  |
| `siteLatitude` | number \\| null |  |
| `siteLongitude` | number \\| null |  |
| `stateCode` | string |  |
| `stateName` | string |  |
| `domainCode` | string |  |
| `domainName` | string |  |
| `deimsId` | string \\| null |  |
| `productCount` | integer |  |
| `latestRelease` | string \\| null |  |
| `urls` | SiteUrls |  |
| `releases` | array of SiteReleaseInfo \\| null |  |
| `dataProducts` | array of SiteProduct \\| null |  |
| `dataProductsPage` | Page \\| null |  |
| `location` | SiteLocation \\| null |  |

## neon_graphql

**Run a NEON GraphQL query.** Read-only GraphQL against NEON's public metadata endpoint for shapes the other tools do not cover. Guard rails: queries only, allow-listed root fields, depth <= 8, one __type/__schema, results pruned to max_bytes with truncatedPaths. No token is sent. Prefer the dedicated tools for products, sites and availability. Next: read neon://reference/graphql-schema for types.

| | |
| --- | --- |
| Surface | `graphql` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `POST /graphql` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `query` | string \\| null |  | null | A read-only GraphQL query against https://data.neonscience.org/graphql (roots: products, product, filterProducts, sites, site, filterSites, location, locationHierarchy, findLocations, prototypeDatasets, prototypeDataset, one __type). |
| `introspect_type` | string \\| null |  | null | Instead of a query: describe one GraphQL type (e.g. Site, DataProductFilter). (pattern `^[_A-Za-z][_0-9A-Za-z]*$`) |
| `variables` | object \\| null |  | null | GraphQL variables. |
| `operation_name` | string \\| null |  | null | Operation to run when the document has several. |
| `max_bytes` | integer |  | `50000` | Response budget; larger lists are pruned. (>= 1000; <= 200000) |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `data` | any |  |
| `errors` | array of object \\| null |  |
| `bytesTotal` | integer |  |
| `truncated` | boolean |  |
| `truncatedPaths` | array of string |  |
| `schemaHint` | string |  |

## neon_list_files

**List NEON data files.** Data files for a product at sites over months (NEON API token required): names, kinds, tables, HOR/VER/TMI, sizes, MD5s and signed URLs (~7 days), plus package ZIP links for a single site-month. detail='summary' or 'site_months' sizes a pull without listing files. Next: call neon_download_files with the same selectors (stdio), or use the URLs.

| | |
| --- | --- |
| Surface | `data` |
| NEON API token | required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /data/{productCode}/{siteCode}/{yearMonth}`<br>`GET /data/{productCode}/{siteCode}/{yearMonth}/{filename}`<br>`POST /data/query` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `product` | string | yes |  | Product code or name. |
| `site_codes` | array of string | yes |  | Site codes or names (up to 30). (min items 1) |
| `start_month` | string | yes |  | First month (YYYY-MM). |
| `end_month` | string \\| null |  | null | Last month (YYYY-MM); defaults to start_month. |
| `package` | `basic` \\| `expanded` |  | `"basic"` | basic (default) or expanded. |
| `release` | string \\| null |  | null | Only files in this release (default: latest per month). |
| `include_provisional` | boolean |  | true | Include PROVISIONAL (unreleased) months. |
| `kind` | `data` \\| `variables` \\| `readme` \\| `sensor_positions` \\| `eml` \\| `science_review_flags` \\| `categorical_codes` \\| `validation` \\| `package` \\| `other` \\| null |  | null | data, variables, readme, sensor_positions, eml, ... or package. |
| `table` | string \\| null |  | null | Table name, e.g. 2DWSD_30min or brd_countdata. |
| `hor` | string \\| null |  | null | Horizontal index, e.g. 000. |
| `ver` | string \\| null |  | null | Vertical index, e.g. 010. |
| `tmi` | string \\| null |  | null | Temporal index in minutes, e.g. 030. |
| `name_contains` | string \\| null |  | null | Substring the file name must contain. |
| `detail` | `files` \\| `site_months` \\| `summary` |  | `"files"` | files (default), site_months (one row per site-month), summary (totals only). |
| `include_urls` | boolean |  | true | Include signed URLs (valid ~7 days; they dominate result size). |
| `filename` | string \\| null |  | null | One exact NEON file name (single site and month): its URL. |
| `limit` | integer |  | `50` | >= 1; <= 200 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `productCode` | string |  |
| `package` | string |  |
| `release` | string \\| null |  |
| `includeProvisional` | boolean |  |
| `siteCodes` | array of string |  |
| `window` | Window |  |
| `detail` | `files` \\| `site_months` \\| `summary` |  |
| `summary` | FileSummary |  |
| `siteMonths` | array of SiteMonthRow \\| null |  |
| `files` | array of FileRecord \\| null |  |
| `packages` | array of PackageLink |  |
| `externalData` | array of ExternalData |  |
| `urlExpiresAt` | string \\| null |  |
| `urlsElided` | boolean |  |
| `curlHint` | string \\| null |  |
| `page` | Page \\| null |  |

## neon_list_releases

**List NEON data releases.** All NEON data releases (RELEASE-2021 ... RELEASE-2026 today), newest first, with generation dates, product counts and manifest artifacts. Releases are immutable and carry per-product DOIs; newer data are PROVISIONAL. Next: call neon_get_release for one release's products and DOIs.

| | |
| --- | --- |
| Surface | `releases` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /releases` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `include_artifact_urls` | boolean |  | false | Include signed manifest URLs (large, expire in 7 days). |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of ReleaseSummary |  |
| `latestRelease` | string \\| null |  |
| `page` | Page |  |

## neon_list_sample_classes

**List NEON sample classes.** NEON's supported sample classes (e.g. bet_IDandpinning_in.individualID) with descriptions, filterable by text, or the classes one sample tag belongs to. No token. Next: call neon_get_sample with a tag and class, a sample UUID, a barcode or an archive GUID.

| | |
| --- | --- |
| Surface | `samples` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /samples/supportedClasses`<br>`GET /samples/classes` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `sample_tag` | string \\| null |  | null | List the classes this sample tag belongs to. |
| `query` | string \\| null |  | null | Substring filter on class key or description. |
| `limit` | integer |  | `50` | >= 1; <= 500 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `sampleTag` | string \\| null |  |
| `items` | array of SampleClass |  |
| `page` | Page |  |
| `sourceEndpoint` | `classes` \\| `supportedClasses` |  |

## neon_ping

**Check neon-mcp status.** Liveness and capability report: server version and protocol, whether a NEON API token is available (it unlocks data files and sample views), whether downloads are enabled, catalog warmth, cache and rate-limit headroom. With check_api=true it makes one ~1 KB NEON request. Never reveals the token. Next: call neon_search_products to find a data product.

| | |
| --- | --- |
| Surface | `core` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /taxonomy` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `check_api` | boolean |  | false | Also make one tiny NEON request (~1 KB) to test reachability and read rate-limit headers. |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `pong` | `ok` |  |
| `version` | string |  |
| `protocolVersion` | string |  |
| `transport` | `stdio` \\| `http` |  |
| `tokenConfigured` | boolean | True when this call has a NEON API token available. |
| `tokenSource` | `config` \\| `request` \\| `none` |  |
| `downloadsEnabled` | boolean |  |
| `downloadDir` | string \\| null |  |
| `apiBaseUrl` | string |  |
| `graphqlUrl` | string |  |
| `catalog` | CatalogStatus |  |
| `cache` | CacheInfo |  |
| `rateLimit` | RateLimitInfo \\| null |  |
| `api` | ApiCheck \\| null |  |

## neon_search_products

**Search NEON data products.** Find NEON data products by keywords, theme, science team, level, status, site, domain or date coverage; ranked results with facets and each product's site count and month range. Served from a cached catalog (no token). A bare code such as DP1.10003.001 matches exactly. Next: call neon_get_availability with a productCode, or neon_get_product for detail.

| | |
| --- | --- |
| Surface | `catalog` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `POST /graphql`<br>`GET /products` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `query` | string \\| null |  | null | Free text (all words must match names, keywords, themes or descriptions; small typos tolerated) or a product code such as DP1.10003.001. |
| `theme` | string \\| null |  | null | Theme prefix, case-insensitive: Atmosphere, Biogeochemistry, Ecohydrology, 'Land Use', 'Organisms'. |
| `science_team` | `AIS` \\| `AOP` \\| `AOS` \\| `TIS` \\| `TOS` \\| null |  | null | TIS, TOS, AIS, AOS or AOP. |
| `status` | `ACTIVE` \\| `FUTURE` \\| `RETIRED` \\| `ALL` |  | `"ACTIVE"` | ACTIVE (default), FUTURE, RETIRED or ALL. |
| `level` | integer \\| null |  | null | Data product level 1-4. (>= 1; <= 4) |
| `has_expanded` | boolean \\| null |  | null | Only products with (or without) an expanded package. |
| `site` | string \\| null |  | null | Only products with data at this site (code or name). |
| `domain_code` | string \\| null |  | null | Only products with data in this domain (D01-D20). |
| `release` | string \\| null |  | null | Evaluate availability within one release (RELEASE-YYYY). |
| `available_from` | string \\| null |  | null | Only products with data on or after this month. |
| `available_to` | string \\| null |  | null | Only products with data on or before this month. |
| `sort` | `relevance` \\| `productCode` \\| `productName` |  | `"relevance"` |  |
| `limit` | integer |  | `25` | >= 1; <= 100 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of ProductSummary |  |
| `page` | Page |  |
| `facets` | object of object of integer |  |
| `didYouMean` | array of string \\| null |  |
| `indexSource` | `graphql` \\| `rest` |  |
| `indexAgeSeconds` | integer |  |

## neon_search_prototype_datasets

**Search NEON prototype datasets.** Search NEON's prototype datasets (early or experimental data outside the standard products) by text, theme, science team, site, years, file type or publication flag, with facets. Each has its own DOI and version. No token. Next: call neon_get_prototype_dataset with a uuid for files.

| | |
| --- | --- |
| Surface | `prototype` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /prototype/datasets` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `query` | string \\| null |  | null | Words in the title, abstract, descriptions or keywords. |
| `theme` | string \\| null |  | null | Data theme prefix, case-insensitive (e.g. 'ecohydrology'). |
| `science_team` | string \\| null |  | null | Team abbreviation or text, e.g. AOS or 'Terrestrial'. |
| `site_code` | string \\| null |  | null | Only datasets covering this site. |
| `start_year` | integer \\| null |  | null | Overlaps this year or later. (>= 1900; <= 2100) |
| `end_year` | integer \\| null |  | null | Overlaps this year or earlier. (>= 1900; <= 2100) |
| `file_type` | string \\| null |  | null | File type such as CSV, PDF, SHP (case-insensitive). |
| `is_published` | boolean \\| null |  | null | Filter on NEON's isPublished flag. |
| `limit` | integer |  | `25` | >= 1; <= 200 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of PrototypeDatasetSummary |  |
| `page` | Page |  |
| `facets` | object of object of integer |  |

## neon_search_sites

**Search NEON field sites.** Find NEON's 81 field sites by code, name, state, domain, site type, product availability or proximity (latitude/longitude + radius_km, nearest first); optional elevation and UTM. Cached catalog, no token. Next: call neon_get_site or neon_get_availability(site=...) for a siteCode.

| | |
| --- | --- |
| Surface | `catalog` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `POST /graphql`<br>`GET /sites`<br>`GET /locations/sites` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `query` | string \\| null |  | null | Site code, name words, or state/domain names ('Harvard', 'Alaska'). |
| `domain_code` | string \\| null |  | null | NEON domain D01-D20. |
| `state_code` | string \\| null |  | null | Two-letter state code (e.g. MA, AK, PR). |
| `site_type` | `CORE` \\| `GRADIENT` \\| null |  | null | CORE or GRADIENT. |
| `product` | string \\| null |  | null | Only sites with data for this product (code or name). |
| `release` | string \\| null |  | null | Sites and products as of one release. |
| `latitude` | number \\| null |  | null | With longitude: nearest sites first. (>= -90; <= 90) |
| `longitude` | number \\| null |  | null | >= -180; <= 180 |
| `radius_km` | number |  | `100.0` | Proximity radius when latitude/longitude are set. (> 0; <= 5000) |
| `include_elevation` | boolean |  | false | Add elevation and UTM (one extra cached request). |
| `limit` | integer |  | `50` | >= 1; <= 100 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of SiteSummary |  |
| `page` | Page |  |
| `facets` | object of object of integer |  |
| `didYouMean` | array of string \\| null |  |
| `indexSource` | `graphql` \\| `rest` |  |
| `indexAgeSeconds` | integer |  |

## neon_search_taxonomy

**Search NEON taxonomy.** NEON's taxonomy lists, paged: every taxon of a type (BIRD, PLANT, SMALL_MAMMAL, ...) or taxa by rank (kingdom ... genus) or exact scientific name with a genus fallback. Rows keep NEON's Darwin Core keys (dwc:scientificName, dwc:vernacularName, ...). No token. Next: follow page.nextOffset, or call neon_search_products for data about the taxa.

| | |
| --- | --- |
| Surface | `taxonomy` |
| NEON API token | not required |
| Transports | http, stdio |
| Annotations | readOnly=true, destructive=false, idempotent=true, openWorld=true |
| NEON endpoints | `GET /taxonomy` |

**Inputs**

| Name | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `taxon_type_code` | `ALGAE` \\| `BEETLE` \\| `BIRD` \\| `FISH` \\| `HERPETOLOGY` \\| `MACROINVERTEBRATE` \\| `MOSQUITO` \\| `MOSQUITO_PATHOGENS` \\| `PLANT` \\| `SMALL_MAMMAL` \\| `TICK` \\| null |  | null | ALGAE, BEETLE, BIRD, FISH, HERPETOLOGY, MACROINVERTEBRATE, MOSQUITO, MOSQUITO_PATHOGENS, PLANT, SMALL_MAMMAL or TICK. Cannot be combined with a rank filter. |
| `kingdom` | string \\| null |  | null |  |
| `phylum` | string \\| null |  | null |  |
| `division` | string \\| null |  | null |  |
| `class_` | string \\| null |  | null | Class (e.g. Aves). |
| `order` | string \\| null |  | null |  |
| `family` | string \\| null |  | null |  |
| `genus` | string \\| null |  | null | Genus, e.g. Quercus. |
| `scientific_name` | string \\| null |  | null | Exact scientific name (NEON matches exactly; a genus fallback runs when nothing matches). |
| `verbose` | boolean |  | false | All ranks and extra fields (nulls dropped); limit capped at 100. |
| `fuzzy_genus_fallback` | boolean |  | true | Retry an unmatched 'Genus species' by genus and filter. |
| `limit` | integer |  | `25` | >= 1; <= 500 |
| `offset` | integer |  | `0` | >= 0 |

**Result fields** (besides the common envelope)

| Field | Type | Description |
| --- | --- | --- |
| `items` | array of object |  |
| `page` | Page |  |
| `filters` | object |  |
| `fuzzyFallbackUsed` | boolean |  |
