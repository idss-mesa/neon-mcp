"""``neon_get_availability``: which sites and months have data (no token)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import ToolError
from neon_mcp.models.common import (
    DomainCode,
    Month,
    NeonInput,
    ProductCode,
    ReleaseTag,
    Resolved,
    Window,
    end_month_field,
    start_month_field,
)
from neon_mcp.neon.resolve import resolve_product, resolve_site, resolve_sites
from neon_mcp.projections.availability import (
    MAX_MONTH_CELLS,
    PROVISIONAL,
    AvailabilityMatrix,
    Cell,
    cell_from_raw,
    month_cells,
    row_from_cell,
    totals,
)
from neon_mcp.projections.common import paginate
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import check_window, source


class GetAvailabilityIn(NeonInput):
    product: str | None = Field(
        None, description="Product code or name. With no site: one row per site."
    )
    site: str | None = Field(
        None, description="Site code or name. With no product: one row per product."
    )
    site_codes: list[str] | None = Field(
        None, max_length=81, description="Product mode: only these sites."
    )
    domain_code: DomainCode | None = Field(
        None, description="Product mode: only sites in this domain."
    )
    product_codes: list[ProductCode] | None = Field(
        None, max_length=200, description="Site mode: only these products."
    )
    release: ReleaseTag | None = Field(
        None, description="Only months in this release (RELEASE-YYYY)."
    )
    provisional: Literal["include", "exclude", "only"] = Field(
        "include",
        description="PROVISIONAL months: include (default), exclude, or only (not with release).",
    )
    start_month: Month | None = start_month_field("Window start (YYYY-MM).")
    end_month: Month | None = end_month_field("Window end (YYYY-MM).")
    format: Literal["ranges", "months", "counts"] | None = Field(
        None,
        description="ranges (default; 'YYYY-MM/YYYY-MM'), months (explicit lists), counts. Cell mode "
        "defaults to months.",
    )
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _combination(self) -> GetAvailabilityIn:
        if not self.product and not self.site:
            raise ValueError("pass product and/or site")
        if self.provisional == "only" and self.release:
            raise ValueError(
                "provisional='only' cannot be combined with release (PROVISIONAL is not a release)"
            )
        if (self.site_codes or self.domain_code) and (self.site or not self.product):
            raise ValueError("site_codes/domain_code filter product mode (product without site)")
        if self.product_codes and (self.product or not self.site):
            raise ValueError("product_codes filters site mode (site without product)")
        return self


@register_tool(
    "neon_get_availability",
    title="Get NEON data availability",
    description=(
        "Which sites and months have data for a product (one row per site), which products have data at a "
        "site (one row per product), or one product-site cell; month ranges per release including "
        "PROVISIONAL, optionally windowed and filtered. Works without a token and is small (GraphQL). "
        "Next: call neon_list_files for a product, site and month range."
    ),
    input_model=GetAvailabilityIn,
    output_model=AvailabilityMatrix,
    surface="catalog",
    endpoints=["POST /graphql", "GET /products/{productCode}", "GET /sites/{siteCode}"],
)
async def neon_get_availability(args: GetAvailabilityIn, ctx: ToolContext) -> AvailabilityMatrix:
    check_window(args.start_month, args.end_month)
    resolved: list[Resolved] = []
    code = site = None
    if args.product:
        code, res = await resolve_product(args.product, ctx)
        resolved += [res] if res else []
    if args.site:
        site, res = await resolve_site(args.site, ctx)
        resolved += [res] if res else []
    mode: Literal["product", "site", "cell"] = (
        "cell" if code and site else ("product" if code else "site")
    )
    fmt = args.format or ("months" if mode == "cell" else "ranges")
    start, end = args.start_month, args.end_month
    notes: list[str] = []
    product_name = site_name = None

    if code is not None:
        site_filter: list[str] | None = [site] if site else None
        if args.site_codes:
            site_filter, res_list = await resolve_sites(args.site_codes, ctx)
            resolved += res_list
        if args.domain_code:
            index = await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)
            domain = sorted(index.domain_sites(args.domain_code))
            site_filter = [s for s in (site_filter or domain) if s in domain]
            if not site_filter:
                raise ToolError(
                    "not_found",
                    f"No NEON sites in {args.domain_code} match.",
                    details={"domainCode": args.domain_code},
                )
        rows_raw, via = await ctx.catalog.product_availability(
            [code],
            site_codes=site_filter,
            start=start,
            end=end,
            release=args.release,
            token=ctx.token,
            stats=ctx.stats,
        )
        product = next((p for p in rows_raw if p.get("productCode") == code), None)
        if product is None:
            raise ToolError(
                "not_found",
                f"product {code!r} was not found.",
                details={"entity": "product", "identifier": code},
                hint="Search with neon_search_products.",
            )
        product_name = product.get("productName")
        names: dict[str, str] = {}
        try:
            names = {
                r.site_code: r.site_name
                for r in (await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)).records
            }
        except Exception:  # names are a nicety; availability must not fail for them
            notes.append("Site names unavailable (site catalog could not be loaded).")
        cells: list[Cell] = [
            cell_from_raw(
                str(s.get("siteCode")),
                names.get(str(s.get("siteCode"))),
                s.get("availableMonths"),
                s.get("availableReleases"),
                start=start,
                end=end,
                provisional=args.provisional,
            )
            for s in product.get("siteCodes") or []
            if not site_filter or s.get("siteCode") in site_filter
        ]
        if site:
            site_name = names.get(site)
    elif site is not None:
        rows_raw, via = await ctx.catalog.site_availability(
            [site],
            product_codes=args.product_codes,
            start=start,
            end=end,
            release=args.release,
            token=ctx.token,
            stats=ctx.stats,
        )
        site_obj = next((s for s in rows_raw if s.get("siteCode") == site), None)
        if site_obj is None:
            raise ToolError(
                "not_found",
                f"site {site!r} was not found.",
                details={"entity": "site", "identifier": site},
                hint="Search with neon_search_sites.",
            )
        site_name = site_obj.get("siteName")
        cells = [
            cell_from_raw(
                str(p.get("dataProductCode")),
                p.get("dataProductTitle"),
                p.get("availableMonths"),
                p.get("availableReleases"),
                start=start,
                end=end,
                provisional=args.provisional,
            )
            for p in site_obj.get("dataProducts") or []
        ]
    else:  # pragma: no cover - the input validator guarantees product or site
        raise ToolError("invalid_argument", "pass product and/or site")

    empty = sum(1 for c in cells if not c.months)
    cells = sorted((c for c in cells if c.months), key=lambda c: c.key)
    if fmt == "months" and month_cells(cells) > MAX_MONTH_CELLS:
        raise ToolError(
            "invalid_argument",
            f"format='months' would list {month_cells(cells)} site-months (limit {MAX_MONTH_CELLS}).",
            hint="Use format='ranges', narrow the window, or filter sites/products.",
        )
    summary = totals(cells)
    page_cells, page = paginate(cells, offset=args.offset, limit=args.limit)
    rows = [row_from_cell(c, mode=mode, fmt=fmt) for c in page_cells]

    if summary.provisional_site_months:
        notes.append(
            f"{summary.provisional_site_months} provisional site-months included (not in any release; may change); "
            "pass provisional='exclude' to drop them."
        )
    if start or end:
        notes.append("Per-release months were clipped to the requested window.")
    if empty:
        notes.append(
            f"{empty} {'site' if mode != 'site' else 'product'}(s) without data in scope were omitted."
        )
    if via == "rest":
        notes.append("GraphQL unavailable; availability computed from the REST detail record.")

    steps: list[str] = []
    if rows:
        top = page_cells[0]
        last = top.months.last()
        if mode == "site":
            steps.append(
                f"neon_get_availability(product='{top.key}', site='{site}') for one product at this site"
            )
        else:
            steps.append(
                f"neon_list_files(product='{code}', site_codes=['{top.key}'], start_month='{last}') "
                "(needs a NEON API token)"
            )
            steps.append(f"neon_get_citation(product='{code}')")
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more rows")
    if not rows:
        steps.append(
            "Widen the window, drop release/provisional filters, or check neon_get_product"
        )

    return AvailabilityMatrix(
        mode=mode,
        product_code=code,
        product_name=product_name,
        site_code=site,
        site_name=site_name,
        release=args.release,
        provisional=args.provisional,
        window=Window(start_month=start, end_month=end) if (start or end) else None,
        format=fmt,
        summary=summary,
        rows=rows,
        page=page,
        resolved=resolved,
        notes=notes,
        next_steps=steps,
        source=source(ctx, via),
    )


__all__ = ["PROVISIONAL", "neon_get_availability"]
