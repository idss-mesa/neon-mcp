"""The GraphQL documents neon-mcp sends to https://data.neonscience.org/graphql.

Each :class:`GqlQuery` pairs a document with the fields its first record
must carry; a missing field is treated as schema drift and triggers the REST
fallback (NEON documents GraphQL as metadata-only, so it can change).
Operation names are stable: the test fixture router keys GraphQL routes by
``operationName``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GqlQuery:
    name: str
    document: str
    expected_fields: tuple[str, ...]
    root: str


def _doc(text: str) -> str:
    return " ".join(text.split())


PRODUCTS_CATALOG = GqlQuery(
    name="NeonMcpProductsCatalog",
    root="products",
    expected_fields=(
        "productCode",
        "productName",
        "productStatus",
        "productScienceTeam",
        "siteCodes",
    ),
    document=_doc(
        """
        query NeonMcpProductsCatalog($release: String) {
          products(release: $release) {
            productCode productName productDescription productStatus productScienceTeam
            productPublicationFormatType productHasExpanded themes keywords
            releases { release generationDate url productDoi { url generationDate } }
            siteCodes { siteCode availableMonths }
            specs { specNumber specDescription specType specSize }
          }
        }
        """
    ),
)

SITES_CATALOG = GqlQuery(
    name="NeonMcpSitesCatalog",
    root="sites",
    expected_fields=(
        "siteCode",
        "siteName",
        "siteType",
        "domainCode",
        "stateCode",
        "siteLatitude",
        "siteLongitude",
        "dataProducts",
    ),
    document=_doc(
        """
        query NeonMcpSitesCatalog($release: String) {
          sites(release: $release) {
            siteCode siteName siteDescription siteType siteLatitude siteLongitude
            stateCode stateName domainCode domainName deimsId
            releases { release generationDate }
            dataProducts { dataProductCode dataProductTitle }
          }
        }
        """
    ),
)

SITES_FOR_RELEASE = GqlQuery(
    name="NeonMcpSitesForRelease",
    root="sites",
    expected_fields=("siteCode", "siteName", "domainCode", "stateCode"),
    document=_doc(
        """
        query NeonMcpSitesForRelease($release: String) {
          sites(release: $release) { siteCode siteName domainCode stateCode }
        }
        """
    ),
)

PRODUCT_AVAILABILITY = GqlQuery(
    name="NeonMcpProductAvailability",
    root="filterProducts",
    expected_fields=("productCode", "siteCodes"),
    document=_doc(
        """
        query NeonMcpProductAvailability($filter: DataProductFilter!) {
          filterProducts(filter: $filter) {
            productCode productName
            siteCodes { siteCode availableMonths availableReleases { release availableMonths } }
          }
        }
        """
    ),
)

SITE_AVAILABILITY = GqlQuery(
    name="NeonMcpSiteAvailability",
    root="filterSites",
    expected_fields=("siteCode", "dataProducts"),
    document=_doc(
        """
        query NeonMcpSiteAvailability($filter: SiteFilter!) {
          filterSites(filter: $filter) {
            siteCode siteName
            dataProducts {
              dataProductCode dataProductTitle availableMonths
              availableReleases { release availableMonths }
            }
          }
        }
        """
    ),
)

LOCATIONS_BATCH = GqlQuery(
    name="NeonMcpLocations",
    root="findLocations",
    expected_fields=("locationName", "locationType"),
    document=_doc(
        """
        query NeonMcpLocations($query: LocationQuery!) {
          findLocations(query: $query) {
            locationName locationType locationDescription siteCode domainCode
            locationDecimalLatitude locationDecimalLongitude locationElevation
            locationUtmEasting locationUtmNorthing locationUtmZone locationUtmHemisphere
            locationParent activePeriods { activatedDate deactivatedDate }
          }
        }
        """
    ),
)

_TYPE_REF = "type { name kind ofType { name kind ofType { name kind ofType { name kind } } } }"

INTROSPECT_ONE = GqlQuery(
    name="NeonMcpIntrospect",
    root="__type",
    expected_fields=("name", "kind"),
    document=_doc(
        f"""
        query NeonMcpIntrospect($name: String!) {{
          __type(name: $name) {{
            name kind description
            fields {{ name description {_TYPE_REF} }}
            inputFields {{ name description {_TYPE_REF} }}
            enumValues {{ name description }}
          }}
        }}
        """
    ),
)

ALL_QUERIES: tuple[GqlQuery, ...] = (
    PRODUCTS_CATALOG,
    SITES_CATALOG,
    SITES_FOR_RELEASE,
    PRODUCT_AVAILABILITY,
    SITE_AVAILABILITY,
    LOCATIONS_BATCH,
    INTROSPECT_ONE,
)


def check_expected_fields(query: GqlQuery, payload: Mapping[str, Any] | None) -> list[str]:
    """Fields of ``query.expected_fields`` missing from the first record (drift)."""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    records = data.get(query.root) if isinstance(data, Mapping) else None
    if records is None:
        return [query.root]
    first = records[0] if isinstance(records, list) and records else records
    if isinstance(records, list) and not records:
        return []
    if not isinstance(first, Mapping):
        return [query.root]
    return [f for f in query.expected_fields if f not in first]
