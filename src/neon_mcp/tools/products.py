"""``neon_search_products`` and ``neon_get_product``."""

from __future__ import annotations

import time
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import (
    DomainCode,
    Month,
    NeonInput,
    Page,
    ProductStatus,
    ReleaseTag,
    Resolved,
    ScienceTeam,
    ToolResultBase,
)
from neon_mcp.neon.catalog import DERIVED_PRODUCT_FIELDS, ProductIndex, ProductQuery, product_record
from neon_mcp.neon.resolve import resolve_product, resolve_site
from neon_mcp.projections.availability import cell_from_raw, row_from_cell
from neon_mcp.projections.common import paginate
from neon_mcp.projections.products import (
    SECTIONS,
    ProductDetail,
    ProductSummary,
    project_product_detail,
    project_product_summary,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, check_window, source

Section = Literal[
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
    "all",
]


class SearchProductsIn(NeonInput):
    query: str | None = Field(
        None,
        description="Free text (all words must match names, keywords, themes or descriptions; small typos "
        "tolerated) or a product code such as DP1.10003.001.",
    )
    theme: str | None = Field(
        None,
        description="Theme prefix, case-insensitive: Atmosphere, Biogeochemistry, Ecohydrology, 'Land Use', "
        "'Organisms'.",
    )
    science_team: ScienceTeam | None = Field(None, description="TIS, TOS, AIS, AOS or AOP.")
    status: ProductStatus = Field("ACTIVE", description="ACTIVE (default), FUTURE, RETIRED or ALL.")
    level: int | None = Field(None, ge=1, le=4, description="Data product level 1-4.")
    has_expanded: bool | None = Field(
        None, description="Only products with (or without) an expanded package."
    )
    site: str | None = Field(
        None, description="Only products with data at this site (code or name)."
    )
    domain_code: DomainCode | None = Field(
        None, description="Only products with data in this domain (D01-D20)."
    )
    release: ReleaseTag | None = Field(
        None, description="Evaluate availability within one release (RELEASE-YYYY)."
    )
    available_from: Month | None = Field(
        None, description="Only products with data on or after this month."
    )
    available_to: Month | None = Field(
        None, description="Only products with data on or before this month."
    )
    sort: Literal["relevance", "productCode", "productName"] = "relevance"
    limit: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0)


class ProductSearchResult(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    items: list[ProductSummary]
    page: Page
    facets: dict[str, dict[str, int]]
    did_you_mean: list[str] | None = None
    index_source: Literal["graphql", "rest"]
    index_age_seconds: int


@register_tool(
    "neon_search_products",
    title="Search NEON data products",
    description=(
        "Find NEON data products by keywords, theme, science team, level, status, site, domain or date "
        "coverage; ranked results with facets and each product's site count and month range. Served from "
        "a cached catalog (no token). A bare code such as DP1.10003.001 matches exactly. Next: call "
        "neon_get_availability with a productCode, or neon_get_product for detail."
    ),
    input_model=SearchProductsIn,
    output_model=ProductSearchResult,
    surface="catalog",
    endpoints=["POST /graphql", "GET /products"],
)
async def neon_search_products(args: SearchProductsIn, ctx: ToolContext) -> ProductSearchResult:
    check_window(args.available_from, args.available_to)
    index = await ctx.catalog.products(release=args.release, token=ctx.token, stats=ctx.stats)
    resolved: list[Resolved] = []
    site_code = None
    if args.site:
        site_code, res = await resolve_site(args.site, ctx)
        if res:
            resolved.append(res)
    domain_sites = None
    if args.domain_code:
        sites = await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)
        domain_sites = sites.domain_sites(args.domain_code)
    result = index.search(
        ProductQuery(
            query=args.query,
            theme=args.theme,
            science_team=args.science_team,
            status=args.status,
            level=args.level,
            has_expanded=args.has_expanded,
            site_code=site_code,
            domain_sites=domain_sites,
            available_from=args.available_from,
            available_to=args.available_to,
            sort=args.sort,
        )
    )
    page_items, page = paginate(result.items, offset=args.offset, limit=args.limit)
    has_query = bool(args.query)
    budget = ctx.config.limits.text_budget_summary
    items = [
        project_product_summary(
            rec,
            score=score if has_query else None,
            matched_on=matched if has_query else None,
            text_budget=budget,
        )
        for rec, score, matched in page_items
    ]
    steps: list[str] = []
    if items:
        first = items[0].product_code
        steps.append(f"neon_get_availability(product='{first}') for sites and months with data")
        steps.append(f"neon_get_product(product='{first}', include=['abstract', 'specs'])")
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for the next {args.limit} products")
    notes: list[str] = []
    if not items:
        steps.append(
            "Relax filters (status='ALL', fewer words, no theme/site) or try a didYouMean term"
        )
    if args.release:
        notes.append(f"Site counts and month ranges reflect {args.release} only.")
    return ProductSearchResult(
        items=items,
        page=page,
        facets=ProductIndex.facets([rec for rec, _, _ in result.items]),
        did_you_mean=result.did_you_mean or None,
        index_source=index.source,
        index_age_seconds=max(int(time.monotonic() - index.built_at), 0),
        resolved=resolved,
        notes=notes,
        next_steps=steps,
        source=source(ctx, derived=DERIVED_PRODUCT_FIELDS if index.source == "graphql" else ()),
    )


class GetProductIn(NeonInput):
    product: str = Field(
        description="Product code (DP1.10003.001, DP1.10003) or name ('breeding landbird')."
    )
    release: ReleaseTag | None = Field(None, description="The product as published in one release.")
    include: list[Section] = Field(
        default_factory=list,
        description="Opt-in sections: abstract, design, study, sensor, remarks, packages, specs, releases, "
        "change_logs, availability, biorepository, or all. Empty = compact base record.",
    )
    change_logs_limit: int = Field(25, ge=1, le=200)
    change_logs_offset: int = Field(0, ge=0)
    availability_limit: int = Field(100, ge=1, le=300)
    availability_offset: int = Field(0, ge=0)
    text_budget: int = Field(
        4000, ge=100, le=20_000, description="Characters kept per text section."
    )

    @model_validator(mode="after")
    def _dedupe(self) -> GetProductIn:
        self.include = list(dict.fromkeys(self.include))
        return self


@register_tool(
    "neon_get_product",
    title="Get a NEON data product",
    description=(
        "One data product: codes, name, team, status, themes, keywords, releases with DOIs and an "
        "availability summary; opt-in include[] sections add abstract and design text, packages, specs "
        "(ATBDs, protocols), change logs (paged), per-site availability rows and biorepository collections. "
        "Accepts a code or a name. Next: call neon_get_availability or neon_get_citation for the product."
    ),
    input_model=GetProductIn,
    output_model=ProductDetail,
    surface="catalog",
    endpoints=["POST /graphql", "GET /products/{productCode}"],
)
async def neon_get_product(args: GetProductIn, ctx: ToolContext) -> ProductDetail:
    code, res = await resolve_product(args.product, ctx)
    include = frozenset(SECTIONS if "all" in args.include else args.include)
    notes: list[str] = []
    raw = None
    if not (include - {"releases"}) and args.release is None:
        index = await ctx.catalog.products(token=ctx.token, stats=ctx.stats)
        rec = index.by_code(code)
        if rec is None:
            raise ToolError(
                "not_found",
                f"product {code!r} is not in the NEON catalog.",
                details={
                    "entity": "product",
                    "identifier": code,
                    "didYouMean": [c.code for c in index.fuzzy_candidates(args.product, 3)],
                },
                hint="Search with neon_search_products.",
            )
        notes.append(
            "Base record from the cached catalog; add include=[...] for text, specs or change logs."
        )
    else:
        try:
            raw = await ctx.catalog.product_detail(
                code, release=args.release, token=ctx.token, stats=ctx.stats
            )
        except NeonApiError as exc:
            raise api_error(
                exc, entity="product", identifier=code, hint="Search with neon_search_products."
            ) from None
        rec = product_record(raw)
        if args.release:
            notes.append(
                f"Scoped to {args.release}: releases and availability reflect that release only."
            )

    availability = None
    if "availability" in include and raw is not None:
        cells = [
            cell_from_raw(
                str(s.get("siteCode")),
                None,
                s.get("availableMonths"),
                s.get("availableReleases"),
                start=None,
                end=None,
                provisional="include",
            )
            for s in raw.get("siteCodes") or []
        ]
        cells = sorted((c for c in cells if c.months), key=lambda c: c.key)
        rows = [row_from_cell(c, mode="product", fmt="ranges") for c in cells]
        availability = paginate(
            rows, offset=args.availability_offset, limit=args.availability_limit
        )

    detail = project_product_detail(
        rec,
        raw,
        include=include,
        text_budget=args.text_budget,
        base_url=ctx.client.base_url,
        change_logs_window=(args.change_logs_offset, args.change_logs_limit),
        availability=availability,
    )
    steps = [
        f"neon_get_availability(product='{code}') for per-site months (released vs provisional)",
        f"neon_get_citation(product='{code}')",
    ]
    if detail.specs:
        steps.append(
            f"neon_get_document(spec_number='{detail.specs[0].spec_number}') for the document"
        )
    if detail.change_logs_page and detail.change_logs_page.next_offset is not None:
        steps.append(
            f"Repeat with change_logs_offset={detail.change_logs_page.next_offset} for more change logs"
        )
    detail.resolved = [res] if res else []
    detail.notes = notes
    detail.next_steps = steps
    detail.source = source(ctx, derived=DERIVED_PRODUCT_FIELDS if raw is None else ())
    return detail
