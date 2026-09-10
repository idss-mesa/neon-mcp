"""Product projections: catalog records / REST detail -> compact models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import Field

from neon_mcp.models.common import MonthRange, NeonOutput, Page, ToolResultBase
from neon_mcp.neon.catalog import ProductRecord
from neon_mcp.neon.months import MonthRanges
from neon_mcp.projections.availability import PROVISIONAL, AvailabilityRow
from neon_mcp.projections.common import clip_text, null_list

PORTAL_PRODUCT_URL = "https://data.neonscience.org/data-products/{code}"
SECTIONS: tuple[str, ...] = (
    "abstract",
    "design",
    "study",
    "sensor",
    "remarks",
    "packages",
    "specs",
    "releases",
    "change_logs",
    "availability",
    "biorepository",
)
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "abstract": ("productAbstract",),
    "design": ("productDesignDescription",),
    "study": ("productStudyDescription",),
    "sensor": ("productSensor",),
    "remarks": ("productRemarks",),
    "packages": ("productBasicDescription", "productExpandedDescription"),
}


class DoiInfo(NeonOutput):
    url: str | None = None
    generation_date: str | None = None


class ReleaseInfo(NeonOutput):
    release: str
    generation_date: str | None = None
    url: str | None = None
    product_doi: DoiInfo | None = None


class AvailabilitySummary(NeonOutput):
    site_count: int
    total_site_months: int
    month_range: MonthRange | None = None
    provisional_site_months: int | None = Field(
        None, description="Provisional site-months; absent when served from the catalog."
    )


class SpecInfo(NeonOutput):
    spec_number: str
    spec_id: str | None = None
    spec_type: str | None = None
    spec_size: int | None = None
    spec_description: str | None = None
    spec_url: str | None = None


class ChangeLog(NeonOutput):
    id: int | str | None = None
    parent_issue_id: int | str | None = Field(None, alias="parentIssueID")
    issue_date: str | None = None
    resolved_date: str | None = None
    date_range_start: str | None = None
    date_range_end: str | None = None
    location_affected: str | None = None
    issue: str | None = None
    resolution: str | None = None


class BiorepositoryCollection(NeonOutput):
    collection_code: str | None = None
    collection_name: str | None = None
    collection_url: str | None = None
    collection_content_url: str | None = None
    collection_download_url: str | None = None


class ProductUrls(NeonOutput):
    portal: str
    api: str


class ProductSummary(NeonOutput):
    product_code: str
    product_name: str
    product_description: str | None = None
    description_truncated: bool = False
    product_status: str
    product_science_team_abbr: str | None = None
    product_category: str
    product_has_expanded: bool
    themes: list[str]
    keywords: list[str]
    keywords_truncated: bool = False
    site_count: int
    month_range: MonthRange | None = None
    latest_release: str | None = None
    score: float | None = None
    matched_on: list[str] | None = None


class ProductCore(NeonOutput):
    product_code: str
    product_code_long: str
    product_code_presentation: str
    product_name: str
    product_description: str | None = None
    product_status: str
    product_category: str
    product_science_team: str | None = None
    product_science_team_abbr: str | None = None
    product_publication_format_type: str | None = None
    product_has_expanded: bool
    themes: list[str]
    keywords: list[str]
    latest_release: str | None = None
    releases: list[ReleaseInfo]
    availability: AvailabilitySummary
    specs_count: int
    change_log_count: int | None = Field(
        None, description="Absent when served from the catalog (no change logs there)."
    )
    urls: ProductUrls


class ProductDetail(ToolResultBase, ProductCore):
    budget_list: ClassVar[str | None] = "availability_rows"
    budget_page: ClassVar[str] = "availability_page"

    product_abstract: str | None = None
    product_design_description: str | None = None
    product_study_description: str | None = None
    product_sensor: str | None = None
    product_remarks: str | None = None
    product_basic_description: str | None = None
    product_expanded_description: str | None = None
    text_truncated: list[str] = Field(
        default_factory=list, description="Text fields clipped to text_budget."
    )
    specs: list[SpecInfo] | None = None
    change_logs: list[ChangeLog] | None = None
    change_logs_page: Page | None = None
    availability_rows: list[AvailabilityRow] | None = None
    availability_page: Page | None = None
    biorepository_collections: list[BiorepositoryCollection] | None = None


def release_infos(rec: ProductRecord) -> list[ReleaseInfo]:
    return [
        ReleaseInfo(
            release=r.release,
            generation_date=r.generation_date,
            url=r.url,
            product_doi=DoiInfo(url=r.doi_url, generation_date=r.doi_generation_date)
            if r.doi_url
            else None,
        )
        for r in sorted(rec.releases, key=lambda r: r.release)
    ]


def provisional_site_months(raw: Mapping[str, Any]) -> int:
    total = 0
    for site in raw.get("siteCodes") or []:
        for entry in site.get("availableReleases") or []:
            if entry.get("release") == PROVISIONAL:
                total += len(entry.get("availableMonths") or [])
    return total


def availability_summary(
    rec: ProductRecord, raw: Mapping[str, Any] | None = None
) -> AvailabilitySummary:
    months = rec.all_months()
    first, last = months.first(), months.last()
    return AvailabilitySummary(
        site_count=len(rec.site_codes()),
        total_site_months=rec.site_month_count(),
        month_range=MonthRange(start=first, end=last) if first and last else None,
        provisional_site_months=provisional_site_months(raw) if raw is not None else None,
    )


def project_product_summary(
    rec: ProductRecord,
    *,
    score: float | None = None,
    matched_on: Sequence[str] | None = None,
    text_budget: int = 300,
) -> ProductSummary:
    description, clipped = clip_text(rec.product_description, text_budget)
    months = rec.all_months()
    first, last = months.first(), months.last()
    return ProductSummary(
        product_code=rec.product_code,
        product_name=rec.product_name,
        product_description=description,
        description_truncated=clipped,
        product_status=rec.product_status,
        product_science_team_abbr=rec.product_science_team_abbr,
        product_category=rec.product_category,
        product_has_expanded=rec.product_has_expanded,
        themes=list(rec.themes),
        keywords=list(rec.keywords[:8]),
        keywords_truncated=len(rec.keywords) > 8,
        site_count=len(rec.site_codes()),
        month_range=MonthRange(start=first, end=last) if first and last else None,
        latest_release=rec.latest_release(),
        score=round(score, 1) if score is not None else None,
        matched_on=list(matched_on) if matched_on else None,
    )


def product_core_fields(
    rec: ProductRecord, raw: Mapping[str, Any] | None, *, base_url: str
) -> dict[str, Any]:
    change_logs = raw.get("changeLogs") if raw is not None else None
    return {
        "product_code": rec.product_code,
        "product_code_long": rec.product_code_long,
        "product_code_presentation": rec.product_code_presentation,
        "product_name": rec.product_name,
        "product_description": rec.product_description or None,
        "product_status": rec.product_status,
        "product_category": rec.product_category,
        "product_science_team": rec.product_science_team or None,
        "product_science_team_abbr": rec.product_science_team_abbr,
        "product_publication_format_type": rec.product_publication_format_type,
        "product_has_expanded": rec.product_has_expanded,
        "themes": list(rec.themes),
        "keywords": list(rec.keywords),
        "latest_release": rec.latest_release(),
        "releases": release_infos(rec),
        "availability": availability_summary(rec, raw),
        "specs_count": len(rec.specs),
        "change_log_count": len(null_list(change_logs)) if raw is not None else None,
        "urls": ProductUrls(
            portal=PORTAL_PRODUCT_URL.format(code=rec.product_code),
            api=f"{base_url}/products/{rec.product_code}",
        ),
    }


def project_product_core(
    rec: ProductRecord, raw: Mapping[str, Any] | None, *, base_url: str
) -> ProductCore:
    return ProductCore(**product_core_fields(rec, raw, base_url=base_url))


def _change_logs(raw: Mapping[str, Any], offset: int, limit: int) -> tuple[list[ChangeLog], Page]:
    from neon_mcp.projections.common import paginate

    logs = null_list(raw.get("changeLogs"))
    logs = sorted(logs, key=lambda c: str(c.get("issueDate") or ""), reverse=True)
    page_items, page = paginate(logs, offset=offset, limit=limit)
    out = []
    for c in page_items:
        issue, _ = clip_text(c.get("issue"), 400)
        resolution, _ = clip_text(c.get("resolution"), 400)
        out.append(
            ChangeLog(
                id=c.get("id"),
                parent_issue_id=c.get("parentIssueID"),
                issue_date=c.get("issueDate"),
                resolved_date=c.get("resolvedDate"),
                date_range_start=c.get("dateRangeStart"),
                date_range_end=c.get("dateRangeEnd"),
                location_affected=c.get("locationAffected"),
                issue=issue,
                resolution=resolution,
            )
        )
    return out, page


def project_product_detail(
    rec: ProductRecord,
    raw: Mapping[str, Any] | None,
    *,
    include: frozenset[str],
    text_budget: int,
    base_url: str,
    change_logs_window: tuple[int, int] = (0, 25),
    availability: tuple[list[AvailabilityRow], Page] | None = None,
) -> ProductDetail:
    fields = product_core_fields(rec, raw, base_url=base_url)
    truncated: list[str] = []
    if raw is not None:
        for section, keys in TEXT_FIELDS.items():
            if section not in include:
                continue
            for key in keys:
                text, clipped = clip_text(raw.get(key), text_budget)
                snake = "".join("_" + ch.lower() if ch.isupper() else ch for ch in key)
                fields[snake] = text
                if clipped:
                    truncated.append(key)
        if "specs" in include:
            fields["specs"] = [
                SpecInfo(
                    spec_number=str(s.get("specNumber")),
                    spec_id=str(s["specId"]) if s.get("specId") is not None else None,
                    spec_type=s.get("specType"),
                    spec_size=s.get("specSize"),
                    spec_description=s.get("specDescription"),
                    spec_url=s.get("specUrl"),
                )
                for s in null_list(raw.get("specs"))
            ]
        if "change_logs" in include:
            logs, page = _change_logs(raw, *change_logs_window)
            fields["change_logs"] = logs
            fields["change_logs_page"] = page
        if "biorepository" in include:
            fields["biorepository_collections"] = [
                BiorepositoryCollection.model_validate(c)
                for c in null_list(raw.get("biorepositoryCollections"))
            ]
    elif "specs" in include:  # pragma: no cover - specs always come from REST
        fields["specs"] = [SpecInfo(spec_number=s.spec_number) for s in rec.specs]
    if availability is not None:
        fields["availability_rows"], fields["availability_page"] = availability
    fields["text_truncated"] = truncated
    return ProductDetail(**fields)


def months_of(rec: ProductRecord, site: str) -> MonthRanges:
    return rec.months_by_site.get(site, MonthRanges())
