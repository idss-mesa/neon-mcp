"""``neon_search_sites`` and ``neon_get_site``."""

from __future__ import annotations

import time
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import (
    DomainCode,
    NeonInput,
    Page,
    ReleaseTag,
    Resolved,
    SiteType,
    StateCode,
    ToolResultBase,
)
from neon_mcp.neon.catalog import SiteIndex, SiteQuery
from neon_mcp.neon.resolve import resolve_product, resolve_site
from neon_mcp.projections.common import paginate
from neon_mcp.projections.sites import (
    SiteDetail,
    SiteReleaseInfo,
    SiteSummary,
    project_site_summary,
    site_core_fields,
    site_location,
    site_products,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source


class SearchSitesIn(NeonInput):
    query: str | None = Field(
        None, description="Site code, name words, or state/domain names ('Harvard', 'Alaska')."
    )
    domain_code: DomainCode | None = Field(None, description="NEON domain D01-D20.")
    state_code: StateCode | None = Field(
        None, description="Two-letter state code (e.g. MA, AK, PR)."
    )
    site_type: SiteType | None = Field(None, description="CORE or GRADIENT.")
    product: str | None = Field(
        None, description="Only sites with data for this product (code or name)."
    )
    release: ReleaseTag | None = Field(None, description="Sites and products as of one release.")
    latitude: float | None = Field(
        None, ge=-90, le=90, description="With longitude: nearest sites first."
    )
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_km: float = Field(
        100.0, gt=0, le=5000, description="Proximity radius when latitude/longitude are set."
    )
    include_elevation: bool = Field(
        False, description="Add elevation and UTM (one extra cached request)."
    )
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _coords(self) -> SearchSitesIn:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("pass latitude and longitude together")
        return self


class SiteSearchResult(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    items: list[SiteSummary]
    page: Page
    facets: dict[str, dict[str, int]]
    did_you_mean: list[str] | None = None
    index_source: Literal["graphql", "rest"]
    index_age_seconds: int


@register_tool(
    "neon_search_sites",
    title="Search NEON field sites",
    description=(
        "Find NEON's 81 field sites by code, name, state, domain, site type, product availability or "
        "proximity (latitude/longitude + radius_km, nearest first); optional elevation and UTM. Cached "
        "catalog, no token. Next: call neon_get_site or neon_get_availability(site=...) for a siteCode."
    ),
    input_model=SearchSitesIn,
    output_model=SiteSearchResult,
    surface="catalog",
    endpoints=["POST /graphql", "GET /sites", "GET /locations/sites"],
)
async def neon_search_sites(args: SearchSitesIn, ctx: ToolContext) -> SiteSearchResult:
    index: SiteIndex = await ctx.catalog.sites(
        release=args.release, token=ctx.token, stats=ctx.stats
    )
    resolved: list[Resolved] = []
    product_sites = None
    if args.product:
        code, res = await resolve_product(args.product, ctx)
        resolved += [res] if res else []
        products = await ctx.catalog.products(
            release=args.release, token=ctx.token, stats=ctx.stats
        )
        rec = products.by_code(code)
        if rec is None:
            raise ToolError(
                "not_found",
                f"product {code!r} is not in the NEON catalog.",
                details={"entity": "product", "identifier": code},
            )
        product_sites = frozenset(rec.site_codes())
    result = index.search(
        SiteQuery(
            query=args.query,
            domain_code=args.domain_code,
            state_code=args.state_code,
            site_type=args.site_type,
            product_sites=product_sites,
            latitude=args.latitude,
            longitude=args.longitude,
            radius_km=args.radius_km,
        )
    )
    distances: dict[str, float] = {}
    if args.latitude is not None and args.longitude is not None:
        distances = {
            r.site_code: d for r, d in index.nearest(args.latitude, args.longitude, args.radius_km)
        }
    elevations: dict[str, Any] = {}
    if args.include_elevation:
        elevations = {
            str(loc.get("siteCode") or loc.get("locationName")): loc
            for loc in await ctx.catalog.site_locations(token=ctx.token, stats=ctx.stats)
        }
    page_items, page = paginate(result.items, offset=args.offset, limit=args.limit)
    has_query = bool(args.query)
    items = [
        project_site_summary(
            rec,
            distance_km=distances.get(rec.site_code),
            elevation=elevations.get(rec.site_code) if elevations else None,
            score=score if has_query else None,
            matched_on=matched if has_query else None,
            text_budget=ctx.config.limits.text_budget_summary,
        )
        for rec, score, matched in page_items
    ]
    steps: list[str] = []
    if items:
        first = items[0].site_code
        steps.append(f"neon_get_site(site='{first}') for its products and releases")
        steps.append(f"neon_get_availability(site='{first}') for product-by-month availability")
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more sites")
    if not items:
        steps.append("Relax filters or increase radius_km")
    return SiteSearchResult(
        items=items,
        page=page,
        facets=SiteIndex.facets([rec for rec, _, _ in result.items]),
        did_you_mean=result.did_you_mean or None,
        index_source=index.source,
        index_age_seconds=max(int(time.monotonic() - index.built_at), 0),
        resolved=resolved,
        next_steps=steps,
        source=source(ctx),
    )


SiteSection = Literal["products", "releases", "description", "location", "all"]


def _default_site_include() -> list[SiteSection]:
    return ["products"]


class GetSiteIn(NeonInput):
    site: str = Field(description="Site code (HARV) or name ('Harvard Forest').")
    release: ReleaseTag | None = Field(None, description="The site as of one release.")
    include: list[SiteSection] = Field(
        default_factory=_default_site_include,
        description="Sections: products (default; per-product month ranges), releases, description (full "
        "text), location (elevation, UTM, properties), all.",
    )
    products_query: str | None = Field(
        None, description="Filter products by code or title substring."
    )
    products_limit: int = Field(100, ge=1, le=300)
    products_offset: int = Field(0, ge=0)


@register_tool(
    "neon_get_site",
    title="Get a NEON field site",
    description=(
        "One field site: name, type, state, domain, coordinates, DEIMS id, and (by default) every data "
        "product available there with month ranges and provisional counts; optional releases, full "
        "description and location record (elevation, UTM, properties). Next: call neon_get_availability "
        "or neon_list_files for a product at this site."
    ),
    input_model=GetSiteIn,
    output_model=SiteDetail,
    surface="catalog",
    endpoints=["GET /sites/{siteCode}", "GET /locations/{locationName}"],
)
async def neon_get_site(args: GetSiteIn, ctx: ToolContext) -> SiteDetail:
    code, res = await resolve_site(args.site, ctx)
    include = (
        {"products", "releases", "description", "location"}
        if "all" in args.include
        else set(args.include)
    )
    try:
        raw = await ctx.catalog.site_detail(
            code, release=args.release, token=ctx.token, stats=ctx.stats
        )
    except NeonApiError as exc:
        raise api_error(
            exc, entity="site", identifier=code, hint="Search with neon_search_sites."
        ) from None
    fields = site_core_fields(
        raw,
        base_url=ctx.client.base_url,
        text_budget=None if "description" in include else ctx.config.limits.text_budget_summary,
    )
    detail = SiteDetail(**fields)
    if "releases" in include:
        detail.releases = [
            SiteReleaseInfo(
                release=str(r.get("release")),
                generation_date=r.get("generationDate"),
                url=r.get("url"),
            )
            for r in raw.get("releases") or []
        ]
    if "products" in include:
        products = site_products(raw, args.products_query)
        detail.data_products, detail.data_products_page = paginate(
            products, offset=args.products_offset, limit=args.products_limit
        )
    if "location" in include:
        env = await ctx.client.get_json(
            f"/locations/{code}", token=ctx.token, stats=ctx.stats, cache="locations"
        )
        detail.location = site_location(env.data or {})
    steps = [f"neon_get_availability(site='{code}') for product-by-month availability"]
    if detail.data_products:
        first = detail.data_products[0]
        last = first.month_range.end if first.month_range else None
        steps.append(
            f"neon_list_files(product='{first.data_product_code}', site_codes=['{code}'], start_month='{last}')"
        )
    if detail.data_products_page and detail.data_products_page.next_offset is not None:
        steps.append(
            f"Repeat with products_offset={detail.data_products_page.next_offset} for more products"
        )
    detail.resolved = [res] if res else []
    detail.next_steps = steps
    detail.source = source(ctx)
    return detail
