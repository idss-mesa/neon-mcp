"""Prototype dataset projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import Field

from neon_mcp.models.common import NeonOutput, Page, ToolResultBase
from neon_mcp.projections.common import clip_text, null_list, parse_gcs_expiry
from neon_mcp.projections.products import DoiInfo


class PrototypeDatasetSummary(NeonOutput):
    uuid: str
    project_title: str
    dataset_abstract: str | None = None
    abstract_truncated: bool = False
    start_year: int | None = None
    end_year: int | None = None
    version: str | None = None
    is_published: bool | None = None
    doi: DoiInfo | None = None
    data_themes: list[str] = Field(default_factory=list)
    science_teams: list[str] = Field(default_factory=list)
    site_codes: list[str] = Field(default_factory=list)
    file_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    date_uploaded: str | None = None


class PrototypeSearchResult(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    items: list[PrototypeDatasetSummary]
    page: Page
    facets: dict[str, dict[str, int]]


class PrototypeFile(NeonOutput):
    name: str | None = None
    description: str | None = None
    file_name: str | None = None
    size: int | None = None
    md5: str | None = None
    type: dict[str, Any] | None = None
    url: str | None = None
    url_expires_at: str | None = None


class PrototypeDatasetDetail(ToolResultBase, PrototypeDatasetSummary):
    budget_list: ClassVar[str | None] = "files"
    budget_page: ClassVar[str] = "files_page"
    budget_elide_fields: ClassVar[tuple[str, ...]] = ("url",)
    budget_elide_flag: ClassVar[str | None] = "urls_elided"

    project_description: str | None = None
    design_description: str | None = None
    metadata_description: str | None = None
    study_area_description: str | None = None
    version_description: str | None = None
    related_versions: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] | None = None
    publication_citations: list[dict[str, Any]] | None = None
    related_data_products: list[dict[str, Any]] | None = None
    data_url: str | None = None
    data_locations: list[dict[str, Any]] = Field(default_factory=list)
    files: list[PrototypeFile] | None = None
    files_page: Page | None = None
    urls_elided: bool = False


def summary_fields(raw: Mapping[str, Any], *, text_budget: int) -> dict[str, Any]:
    abstract, clipped = clip_text(raw.get("datasetAbstract"), text_budget)
    doi = raw.get("doi")
    return {
        "uuid": str(raw.get("uuid")),
        "project_title": str(raw.get("projectTitle") or ""),
        "dataset_abstract": abstract,
        "abstract_truncated": clipped,
        "start_year": raw.get("startYear"),
        "end_year": raw.get("endYear"),
        "version": raw.get("version"),
        "is_published": raw.get("isPublished"),
        "doi": DoiInfo(url=doi.get("url"), generation_date=doi.get("generationDate"))
        if isinstance(doi, Mapping)
        else None,
        "data_themes": list(null_list(raw.get("dataThemes"))),
        "science_teams": list(null_list(raw.get("scienceTeams"))),
        "site_codes": sorted(
            {
                str(loc.get("siteCode"))
                for loc in null_list(raw.get("locations"))
                if loc.get("siteCode")
            }
        ),
        "file_types": [
            str(f.get("name")) for f in null_list(raw.get("fileTypes")) if f.get("name")
        ],
        "keywords": list(null_list(raw.get("keywords")))[:8],
        "date_uploaded": raw.get("dateUploaded"),
    }


def project_prototype_summary(
    raw: Mapping[str, Any], *, text_budget: int = 300
) -> PrototypeDatasetSummary:
    return PrototypeDatasetSummary(**summary_fields(raw, text_budget=text_budget))


def project_file(raw: Mapping[str, Any], *, include_url: bool) -> PrototypeFile:
    url = raw.get("url")
    return PrototypeFile(
        name=raw.get("name"),
        description=raw.get("description"),
        file_name=raw.get("fileName"),
        size=raw.get("size") if raw.get("size") is not None else raw.get("fileSize"),
        md5=raw.get("md5"),
        type=raw.get("type"),
        url=url if include_url else None,
        url_expires_at=parse_gcs_expiry(url) if include_url else None,
    )
