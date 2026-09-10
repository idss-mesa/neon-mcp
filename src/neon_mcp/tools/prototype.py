"""``neon_search_prototype_datasets`` and ``neon_get_prototype_dataset``."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError
from neon_mcp.models.common import NeonInput, SiteCode, Uuid
from neon_mcp.neon.catalog import words
from neon_mcp.projections.common import clip_text, null_list, paginate
from neon_mcp.projections.prototype import (
    PrototypeDatasetDetail,
    PrototypeSearchResult,
    project_file,
    project_prototype_summary,
    summary_fields,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source


class SearchPrototypeIn(NeonInput):
    query: str | None = Field(
        None, description="Words in the title, abstract, descriptions or keywords."
    )
    theme: str | None = Field(
        None, description="Data theme prefix, case-insensitive (e.g. 'ecohydrology')."
    )
    science_team: str | None = Field(
        None, description="Team abbreviation or text, e.g. AOS or 'Terrestrial'."
    )
    site_code: SiteCode | None = Field(None, description="Only datasets covering this site.")
    start_year: int | None = Field(
        None, ge=1900, le=2100, description="Overlaps this year or later."
    )
    end_year: int | None = Field(
        None, ge=1900, le=2100, description="Overlaps this year or earlier."
    )
    file_type: str | None = Field(
        None, description="File type such as CSV, PDF, SHP (case-insensitive)."
    )
    is_published: bool | None = Field(None, description="Filter on NEON's isPublished flag.")
    limit: int = Field(25, ge=1, le=200)
    offset: int = Field(0, ge=0)


def _matches(raw: Mapping[str, Any], args: SearchPrototypeIn) -> bool:
    if args.query:
        haystack = set(
            words(
                " ".join(
                    str(raw.get(k) or "")
                    for k in (
                        "projectTitle",
                        "datasetAbstract",
                        "projectDescription",
                        "designDescription",
                    )
                )
            )
        ) | {w for k in null_list(raw.get("keywords")) for w in words(str(k))}
        if not all(w in haystack for w in words(args.query)):
            return False
    if args.theme and not any(
        str(t).lower().startswith(args.theme.lower()) for t in null_list(raw.get("dataThemes"))
    ):
        return False
    if args.science_team:
        team = args.science_team.lower()
        if not any(team in str(t).lower() for t in null_list(raw.get("scienceTeams"))):
            return False
    if args.site_code and args.site_code not in {
        loc.get("siteCode") for loc in null_list(raw.get("locations"))
    }:
        return False
    start, end = raw.get("startYear"), raw.get("endYear")
    if args.start_year is not None and (end or start or 0) < args.start_year:
        return False
    if args.end_year is not None and (start or end or 9999) > args.end_year:
        return False
    if args.file_type and args.file_type.lower() not in {
        str(f.get("name", "")).lower() for f in null_list(raw.get("fileTypes"))
    }:
        return False
    return not (args.is_published is not None and bool(raw.get("isPublished")) != args.is_published)


@register_tool(
    "neon_search_prototype_datasets",
    title="Search NEON prototype datasets",
    description=(
        "Search NEON's prototype datasets (early or experimental data outside the standard products) by "
        "text, theme, science team, site, years, file type or publication flag, with facets. Each has "
        "its own DOI and version. No token. Next: call neon_get_prototype_dataset with a uuid for files."
    ),
    input_model=SearchPrototypeIn,
    output_model=PrototypeSearchResult,
    surface="prototype",
    endpoints=["GET /prototype/datasets"],
)
async def neon_search_prototype_datasets(
    args: SearchPrototypeIn, ctx: ToolContext
) -> PrototypeSearchResult:
    datasets = await ctx.catalog.prototype_datasets(token=ctx.token, stats=ctx.stats)
    matched = sorted(
        (d for d in datasets if _matches(d, args)), key=lambda d: str(d.get("projectTitle") or "")
    )
    page_items, page = paginate(matched, offset=args.offset, limit=args.limit)
    facets = {
        "dataThemes": dict(
            sorted(Counter(t for d in matched for t in null_list(d.get("dataThemes"))).items())
        ),
        "scienceTeams": dict(
            sorted(Counter(t for d in matched for t in null_list(d.get("scienceTeams"))).items())
        ),
        "fileTypes": dict(
            sorted(
                Counter(
                    str(f.get("name")) for d in matched for f in null_list(d.get("fileTypes"))
                ).items()
            )
        ),
    }
    items = [
        project_prototype_summary(d, text_budget=ctx.config.limits.text_budget_summary)
        for d in page_items
    ]
    steps = (
        [f"neon_get_prototype_dataset(uuid='{items[0].uuid}') for files and descriptions"]
        if items
        else ["Relax filters (theme, science_team, file_type)"]
    )
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more datasets")
    return PrototypeSearchResult(
        items=items, page=page, facets=facets, next_steps=steps, source=source(ctx)
    )


class GetPrototypeIn(NeonInput):
    uuid: Uuid = Field(description="Prototype dataset uuid.")
    include: list[Literal["files", "descriptions", "locations", "citations", "related", "all"]] = (
        Field(
            default_factory=lambda: ["files", "locations"],  # type: ignore[arg-type]
            description="files (default; signed URLs), locations (default), descriptions, citations, related, all.",
        )
    )
    include_urls: bool = Field(True, description="Include signed download URLs (valid ~7 days).")
    files_limit: int = Field(100, ge=1, le=500)
    files_offset: int = Field(0, ge=0)
    text_budget: int = Field(4000, ge=100, le=20_000)


@register_tool(
    "neon_get_prototype_dataset",
    title="Get a NEON prototype dataset",
    description=(
        "One prototype dataset: title, abstract, years, version, DOI, themes, teams, sites, and by default "
        "its files with sizes, MD5s and signed URLs; optional project/design/metadata descriptions, "
        "publication citations and related products. Next: call neon_download_files(prototype_uuid=...) "
        "on stdio, or neon_get_citation(prototype_uuid=...)."
    ),
    input_model=GetPrototypeIn,
    output_model=PrototypeDatasetDetail,
    surface="prototype",
    endpoints=["GET /prototype/datasets/{uuid}", "GET /prototype/data/{uuid}"],
)
async def neon_get_prototype_dataset(
    args: GetPrototypeIn, ctx: ToolContext
) -> PrototypeDatasetDetail:
    include = (
        {"files", "descriptions", "locations", "citations", "related"}
        if "all" in args.include
        else set(args.include)
    )
    try:
        env = await ctx.client.get_json(
            f"/prototype/datasets/{args.uuid}", token=ctx.token, stats=ctx.stats, cache="detail"
        )
    except NeonApiError as exc:
        raise api_error(
            exc,
            entity="prototype dataset",
            identifier=args.uuid,
            hint="Search with neon_search_prototype_datasets.",
        ) from None
    raw = env.data or {}
    detail = PrototypeDatasetDetail(**summary_fields(raw, text_budget=args.text_budget))
    data = raw.get("data") or {}
    detail.data_url = data.get("url")
    detail.data_locations = [dict(x) for x in null_list(data.get("dataLocations"))]
    detail.related_versions = [dict(x) for x in null_list(raw.get("relatedVersions"))]
    if "descriptions" in include:
        for field, key in (
            ("project_description", "projectDescription"),
            ("design_description", "designDescription"),
            ("metadata_description", "metadataDescription"),
            ("study_area_description", "studyAreaDescription"),
            ("version_description", "versionDescription"),
        ):
            setattr(detail, field, clip_text(raw.get(key), args.text_budget)[0])
    if "locations" in include:
        detail.locations = [dict(x) for x in null_list(raw.get("locations"))]
    if "citations" in include:
        detail.publication_citations = [dict(x) for x in null_list(raw.get("publicationCitations"))]
    if "related" in include:
        detail.related_data_products = [dict(x) for x in null_list(raw.get("relatedDataProducts"))]
    if "files" in include:
        try:
            files_env = await ctx.client.get_json(
                f"/prototype/data/{args.uuid}", token=ctx.token, stats=ctx.stats, cache="data"
            )
        except NeonApiError as exc:
            raise api_error(exc, entity="prototype dataset files", identifier=args.uuid) from None
        files = [
            project_file(f, include_url=args.include_urls)
            for f in null_list((files_env.data or {}).get("files"))
        ]
        detail.files, detail.files_page = paginate(
            files, offset=args.files_offset, limit=args.files_limit
        )
    steps = [f"neon_get_citation(prototype_uuid='{args.uuid}')"]
    if ctx.config.effective_downloads_enabled(ctx.transport):
        steps.insert(
            0, f"neon_download_files(prototype_uuid='{args.uuid}') to save the files locally"
        )
    notes = (
        ["Signed URLs expire about 7 days after generation (urlExpiresAt)."] if detail.files else []
    )
    detail.notes = notes
    detail.next_steps = steps
    detail.source = source(ctx)
    return detail
