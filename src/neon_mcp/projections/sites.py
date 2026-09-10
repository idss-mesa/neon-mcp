"""Site projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import Field

from neon_mcp.models.common import MonthRange, NeonOutput, Page, ToolResultBase
from neon_mcp.neon.catalog import SiteRecord, site_record
from neon_mcp.neon.months import MonthRanges
from neon_mcp.projections.common import clip_text, null_list, properties_map

PORTAL_SITE_URL = "https://www.neonscience.org/field-sites/{code}"


class SiteSummary(NeonOutput):
    site_code: str
    site_name: str
    site_description: str | None = None
    description_truncated: bool = False
    site_type: str
    site_latitude: float | None = None
    site_longitude: float | None = None
    state_code: str
    state_name: str
    domain_code: str
    domain_name: str
    product_count: int
    latest_release: str | None = None
    distance_km: float | None = None
    location_elevation: float | None = None
    location_utm_zone: int | None = None
    location_utm_easting: float | None = None
    location_utm_northing: float | None = None
    location_utm_hemisphere: str | None = None
    score: float | None = None
    matched_on: list[str] | None = None


class SiteUrls(NeonOutput):
    portal: str
    api: str


class SiteReleaseInfo(NeonOutput):
    release: str
    generation_date: str | None = None
    url: str | None = None


class SiteProduct(NeonOutput):
    data_product_code: str
    data_product_title: str | None = None
    month_count: int
    month_range: MonthRange | None = None
    ranges: list[str]
    provisional_months: int = 0


class SiteLocation(NeonOutput):
    location_elevation: float | None = None
    location_utm_easting: float | None = None
    location_utm_northing: float | None = None
    location_utm_zone: int | None = None
    location_utm_hemisphere: str | None = None
    location_properties: dict[str, Any] = Field(default_factory=dict)
    active_periods: list[dict[str, Any]] = Field(default_factory=list)


class SiteCore(NeonOutput):
    site_code: str
    site_name: str
    site_description: str | None = None
    site_type: str
    site_latitude: float | None = None
    site_longitude: float | None = None
    state_code: str
    state_name: str
    domain_code: str
    domain_name: str
    deims_id: str | None = None
    product_count: int
    latest_release: str | None = None
    urls: SiteUrls


class SiteDetail(ToolResultBase, SiteCore):
    budget_list: ClassVar[str | None] = "data_products"
    budget_page: ClassVar[str] = "data_products_page"

    releases: list[SiteReleaseInfo] | None = None
    data_products: list[SiteProduct] | None = None
    data_products_page: Page | None = None
    location: SiteLocation | None = None


def project_site_summary(
    rec: SiteRecord,
    *,
    distance_km: float | None = None,
    elevation: Mapping[str, Any] | None = None,
    score: float | None = None,
    matched_on: list[str] | None = None,
    text_budget: int = 300,
) -> SiteSummary:
    description, clipped = clip_text(rec.site_description, text_budget)
    extra: dict[str, Any] = {}
    if elevation is not None:
        extra = {
            "location_elevation": elevation.get("locationElevation"),
            "location_utm_zone": elevation.get("locationUtmZone"),
            "location_utm_easting": elevation.get("locationUtmEasting"),
            "location_utm_northing": elevation.get("locationUtmNorthing"),
            "location_utm_hemisphere": elevation.get("locationUtmHemisphere"),
        }
    return SiteSummary(
        site_code=rec.site_code,
        site_name=rec.site_name,
        site_description=description,
        description_truncated=clipped,
        site_type=rec.site_type,
        site_latitude=rec.latitude,
        site_longitude=rec.longitude,
        state_code=rec.state_code,
        state_name=rec.state_name,
        domain_code=rec.domain_code,
        domain_name=rec.domain_name,
        product_count=len(rec.product_codes),
        latest_release=rec.latest_release(),
        distance_km=distance_km,
        score=round(score, 1) if score is not None else None,
        matched_on=matched_on or None,
        **extra,
    )


def site_core_fields(
    raw: Mapping[str, Any], *, base_url: str, text_budget: int | None = None
) -> dict[str, Any]:
    rec = site_record(raw)
    description = rec.site_description or None
    if text_budget is not None:
        description, _ = clip_text(description, text_budget)
    return {
        "site_code": rec.site_code,
        "site_name": rec.site_name,
        "site_description": description,
        "site_type": rec.site_type,
        "site_latitude": rec.latitude,
        "site_longitude": rec.longitude,
        "state_code": rec.state_code,
        "state_name": rec.state_name,
        "domain_code": rec.domain_code,
        "domain_name": rec.domain_name,
        "deims_id": rec.deims_id,
        "product_count": len(rec.product_codes),
        "latest_release": rec.latest_release(),
        "urls": SiteUrls(
            portal=PORTAL_SITE_URL.format(code=rec.site_code.lower()),
            api=f"{base_url}/sites/{rec.site_code}",
        ),
    }


def site_products(raw: Mapping[str, Any], query: str | None) -> list[SiteProduct]:
    out: list[SiteProduct] = []
    needle = (query or "").lower().strip()
    for p in null_list(raw.get("dataProducts")):
        code = str(p.get("dataProductCode") or "")
        title = p.get("dataProductTitle")
        if needle and needle not in code.lower() and needle not in str(title or "").lower():
            continue
        months = MonthRanges.from_months(p.get("availableMonths") or [])
        provisional = sum(
            len(r.get("availableMonths") or [])
            for r in null_list(p.get("availableReleases"))
            if r.get("release") == "PROVISIONAL"
        )
        first, last = months.first(), months.last()
        out.append(
            SiteProduct(
                data_product_code=code,
                data_product_title=title,
                month_count=months.count(),
                month_range=MonthRange(start=first, end=last) if first and last else None,
                ranges=months.ranges(),
                provisional_months=provisional,
            )
        )
    return sorted(out, key=lambda p: p.data_product_code)


def site_location(raw: Mapping[str, Any]) -> SiteLocation:
    props, _ = properties_map(raw.get("locationProperties"))
    return SiteLocation(
        location_elevation=raw.get("locationElevation"),
        location_utm_easting=raw.get("locationUtmEasting"),
        location_utm_northing=raw.get("locationUtmNorthing"),
        location_utm_zone=raw.get("locationUtmZone"),
        location_utm_hemisphere=raw.get("locationUtmHemisphere"),
        location_properties=props,
        active_periods=[dict(p) for p in null_list(raw.get("activePeriods"))],
    )
