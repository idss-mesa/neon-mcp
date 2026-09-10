# NEON GraphQL schema (for neon_graphql)

Endpoint: `https://data.neonscience.org/graphql` (public; not under `/api/v0`).
NEON documents GraphQL as metadata only: no data files, taxonomy, samples or
releases list. Introspected 2026-09-10; use `neon_graphql(introspect_type="Site")`
to see any type live (one `__type` or `__schema` per query — NEON rejects more
as `BadFaithIntrospection`).

## Root fields

| Field | Arguments | Returns |
|---|---|---|
| `products` | `release: String` | `[DataProduct]` (all 202 products) |
| `product` | `productCode: String!`, `release` | `DataProduct` |
| `filterProducts` | `filter: DataProductFilter!` | `[DataProduct]` with windowed availability |
| `sites` | `release: String` | `[Site]` (81 field sites) |
| `site` | `siteCode: String!`, `release` | `Site` |
| `filterSites` | `filter: SiteFilter!` | `[Site]` with windowed availability |
| `location` | `name: String!` | `Location` |
| `locationHierarchy` | `name: String!`, `locationType` | `Location` with child hierarchy |
| `findLocations` | `query: LocationQuery!` | `[Location]` (batch by name) |
| `prototypeDatasets` / `prototypeDataset` | — / `uuid: String!` | `PrototypeDataset` |

## Inputs

* `DataProductFilter { productCodes: [String]!, siteCodes: [String], startMonth: "YYYY-MM", endMonth: "YYYY-MM", release: String }`
* `SiteFilter { siteCodes: [String]!, productCodes: [String], startMonth, endMonth, release }`
* `LocationQuery { locationNames: [String]! }`

`availableMonths` is windowed by `startMonth`/`endMonth`, but
`availableReleases[].availableMonths` is **not** (clip it yourself).
`release: "PROVISIONAL"` is rejected ("Release not found").

## Main object fields

* `DataProduct`: productCode, productName, productDescription, productStatus,
  productScienceTeam, productPublicationFormatType, productAbstract,
  productHasExpanded, productBasicDescription, productExpandedDescription,
  themes, keywords, specs { specNumber specDescription specType specSize },
  releases { release generationDate url productDoi { url generationDate } },
  siteCodes { siteCode availableMonths availableDataUrls availableReleases { release availableMonths } }.
* `Site`: siteCode, siteName, siteDescription, siteType, siteLatitude,
  siteLongitude, stateCode, stateName, domainCode, domainName, deimsId,
  releases, dataProducts { dataProductCode dataProductTitle availableMonths availableReleases }.
* `Location`: locationName, locationType, locationDescription, siteCode,
  domainCode, locationDecimalLatitude/Longitude, locationElevation,
  locationUtmEasting/Northing/Zone/Hemisphere, alpha/beta/gammaOrientation,
  x/y/zOffset, activePeriods, locationProperties, locationHistory,
  locationParent, locationChildren, locationChildHierarchy.

## Not in GraphQL (REST only)

productScienceTeamAbbr, productCategory, productCodeLong, change logs,
spec URLs, productSensor, productRemarks, biorepository collections,
taxonomy, samples, releases list, data files, documents.
