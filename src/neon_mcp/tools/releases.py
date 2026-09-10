"""``neon_list_releases``, ``neon_get_release`` and ``neon_get_citation``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from string import Template
from typing import Any, Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import NeonInput, Page, ProductCode, ReleaseId, SiteCode, Uuid
from neon_mcp.neon.catalog import product_record
from neon_mcp.neon.resolve import resolve_product, resolve_sites
from neon_mcp.projections.common import paginate
from neon_mcp.projections.products import project_product_core
from neon_mcp.projections.releases import (
    Citation,
    ReleaseDetail,
    ReleaseList,
    ReleaseSite,
    artifacts,
    bare_doi,
    project_release_summary,
    release_products,
)
from neon_mcp.projections.sites import SiteCore, site_core_fields
from neon_mcp.registry import register_tool
from neon_mcp.resources import citation_templates
from neon_mcp.tools._common import api_error, source

PORTAL = "https://data.neonscience.org"


def _release_sort_key(raw: dict[str, Any]) -> str:
    return str(raw.get("release") or "")


class ListReleasesIn(NeonInput):
    include_artifact_urls: bool = Field(
        False, description="Include signed manifest URLs (large, expire in 7 days)."
    )


@register_tool(
    "neon_list_releases",
    title="List NEON data releases",
    description=(
        "All NEON data releases (RELEASE-2021 ... RELEASE-2026 today), newest first, with generation dates, "
        "product counts and manifest artifacts. Releases are immutable and carry per-product DOIs; newer "
        "data are PROVISIONAL. Next: call neon_get_release for one release's products and DOIs."
    ),
    input_model=ListReleasesIn,
    output_model=ReleaseList,
    surface="releases",
    endpoints=["GET /releases"],
)
async def neon_list_releases(args: ListReleasesIn, ctx: ToolContext) -> ReleaseList:
    releases = sorted(
        await ctx.catalog.releases(token=ctx.token, stats=ctx.stats),
        key=_release_sort_key,
        reverse=True,
    )
    items = [
        project_release_summary(r, include_artifact_urls=args.include_artifact_urls)
        for r in releases
    ]
    latest = items[0].release if items else None
    return ReleaseList(
        items=items,
        latest_release=latest,
        page=Page(
            total=len(items),
            returned=len(items),
            offset=0,
            limit=max(len(items), 1),
            truncated=False,
        ),
        next_steps=[f"neon_get_release(release='{latest}') for its products and DOIs"]
        if latest
        else [],
        notes=["PROVISIONAL data are not part of any release; they may change until released."],
        source=source(ctx),
    )


async def _resolve_release(identifier: str, ctx: ToolContext) -> str:
    if identifier.startswith("RELEASE-"):
        return identifier
    releases = await ctx.catalog.releases(token=ctx.token, stats=ctx.stats)
    tags = sorted(str(r.get("release")) for r in releases if r.get("release"))
    if identifier == "latest":
        if not tags:
            raise ToolError("not_found", "NEON returned no releases.")
        return tags[-1]
    for r in releases:
        if str(r.get("uuid", "")).lower() == identifier:
            return str(r.get("release"))
    raise ToolError(
        "not_found",
        f"No release has uuid {identifier!r}.",
        details={"entity": "release", "identifier": identifier, "validReleases": tags},
    )


ReleaseSection = Literal["products", "sites", "artifacts", "all"]


def _default_release_include() -> list[ReleaseSection]:
    return ["products"]


class GetReleaseIn(NeonInput):
    release: ReleaseId = Field(description="RELEASE-YYYY, a release uuid, or 'latest'.")
    include: list[ReleaseSection] = Field(
        default_factory=_default_release_include,
        description="products (default; codes, names, DOIs), sites (codes and names), artifacts (manifests), all.",
    )
    product_query: str | None = Field(
        None, description="Filter products by code or name substring."
    )
    products_limit: int = Field(50, ge=1, le=500)
    products_offset: int = Field(0, ge=0)
    product_code: ProductCode | None = Field(
        None, description="Also return this product as published in the release."
    )
    site_code: SiteCode | None = Field(
        None, description="Also return this site as published in the release."
    )
    include_artifact_urls: bool = Field(False, description="Include signed manifest URLs.")


@register_tool(
    "neon_get_release",
    title="Get a NEON data release",
    description=(
        "One release (tag, uuid or 'latest'): its data products with DOIs (paged, filterable), optionally "
        "its sites and manifest artifacts, or one product/site exactly as published in that release. "
        "Unknown tags fail with the list of valid releases. Next: call neon_get_citation for a product in "
        "the release."
    ),
    input_model=GetReleaseIn,
    output_model=ReleaseDetail,
    surface="releases",
    endpoints=[
        "GET /releases/{releaseIdentifier}",
        "POST /graphql",
        "GET /releases/{releaseTag}/products/{productCode}",
        "GET /releases/{releaseTag}/sites/{siteCode}",
    ],
)
async def neon_get_release(args: GetReleaseIn, ctx: ToolContext) -> ReleaseDetail:
    tag = await _resolve_release(args.release, ctx)
    include = {"products", "sites", "artifacts"} if "all" in args.include else set(args.include)
    try:
        raw = await ctx.catalog.release_detail(tag, token=ctx.token, stats=ctx.stats)
    except NeonApiError as exc:
        raise api_error(exc, entity="release", identifier=tag) from None
    notes: list[str] = []
    detail = ReleaseDetail(
        release=str(raw.get("release") or tag),
        uuid=raw.get("uuid"),
        generation_date=raw.get("generationDate"),
        product_count=len(raw.get("dataProducts") or []),
    )
    if "products" in include:
        detail.data_products, detail.products_page = paginate(
            release_products(raw, args.product_query),
            offset=args.products_offset,
            limit=args.products_limit,
        )
    if "artifacts" in include:
        detail.artifacts = artifacts(raw, include_urls=args.include_artifact_urls)
    if "sites" in include:
        rows = await ctx.catalog.sites_for_release(tag, token=ctx.token, stats=ctx.stats)
        if rows is None:
            notes.append(
                "Site list unavailable (GraphQL failed); the 22 MB REST site mirror is never fetched."
            )
        else:
            detail.sites = [
                ReleaseSite(
                    site_code=str(r.get("siteCode")),
                    site_name=r.get("siteName"),
                    domain_code=r.get("domainCode"),
                    state_code=r.get("stateCode"),
                )
                for r in sorted(rows, key=lambda r: str(r.get("siteCode")))
            ]
    if args.product_code:
        try:
            env = await ctx.client.get_json(
                f"/releases/{tag}/products/{args.product_code}",
                token=ctx.token,
                stats=ctx.stats,
                cache="detail",
            )
        except NeonApiError as exc:
            raise api_error(
                exc, entity="product", identifier=f"{args.product_code} in {tag}"
            ) from None
        prod = env.data or {}
        detail.product = project_product_core(
            product_record(prod), prod, base_url=ctx.client.base_url
        )
    if args.site_code:
        try:
            env = await ctx.client.get_json(
                f"/releases/{tag}/sites/{args.site_code}",
                token=ctx.token,
                stats=ctx.stats,
                cache="detail",
            )
        except NeonApiError as exc:
            raise api_error(exc, entity="site", identifier=f"{args.site_code} in {tag}") from None
        detail.site = SiteCore(
            **site_core_fields(env.data or {}, base_url=ctx.client.base_url, text_budget=300)
        )
    steps = []
    if detail.data_products:
        first = detail.data_products[0].product_code
        steps.append(f"neon_get_citation(product='{first}', release='{detail.release}')")
    if detail.products_page and detail.products_page.next_offset is not None:
        steps.append(
            f"Repeat with products_offset={detail.products_page.next_offset} for more products"
        )
    detail.notes = notes
    detail.next_steps = steps or ["neon_list_releases() for every release"]
    detail.source = source(ctx)
    return detail


class GetCitationIn(NeonInput):
    product: str | None = Field(None, description="Product code or name.")
    prototype_uuid: Uuid | None = Field(None, description="Cite a prototype dataset instead.")
    release: ReleaseId = Field(
        "latest", description="RELEASE-YYYY, a release uuid, or 'latest' (newest with a DOI)."
    )
    provisional: bool = Field(
        False, description="Cite provisional data (no DOI). Not with an explicit release."
    )
    format: Literal["text", "bibtex", "all"] = "all"
    accessed_on: date | None = Field(
        None, description="Access date for the citation (default: today, UTC)."
    )
    site_codes: list[str] | None = Field(
        None, max_length=81, description="Sites the data came from (noted)."
    )

    @model_validator(mode="after")
    def _mode(self) -> GetCitationIn:
        if (self.product is None) == (self.prototype_uuid is None):
            raise ValueError("pass exactly one of product or prototype_uuid")
        if self.provisional and self.release != "latest":
            raise ValueError(
                "provisional=true cites provisional data, which has no release; omit release"
            )
        return self


def _accessed(value: date | None) -> str:
    day = value or datetime.now(UTC).date()
    return f"{day:%B} {day.day}, {day.year}"


def _bibtex(key: str, *, title: str, year: str, doi: str | None, url: str, accessed: str) -> str:
    text = Template(citation_templates().bibtex).substitute(
        key=key, title=title, year=year, doi=doi or "", url=url, accessedOn=accessed
    )
    if not doi:
        text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("doi ="))
    return text


@register_tool(
    "neon_get_citation",
    title="Cite NEON data",
    description=(
        "NEON-format citation text and BibTeX for a data product in a release (DOI, default the newest "
        "release with a DOI), for provisional data (no DOI; archive what you used), or for a prototype "
        "dataset. Wording follows NEON's data policy (CC BY 4.0). Next: include the citation with any "
        "results; read neon://guide/citing-neon-data for the rules."
    ),
    input_model=GetCitationIn,
    output_model=Citation,
    surface="releases",
    endpoints=["GET /releases", "GET /prototype/datasets/{uuid}"],
)
async def neon_get_citation(args: GetCitationIn, ctx: ToolContext) -> Citation:
    templates = citation_templates()
    accessed = _accessed(args.accessed_on)
    notes: list[str] = []
    if args.site_codes:
        codes, _ = await resolve_sites(args.site_codes, ctx)
        notes.append(f"Data for sites {', '.join(codes)}.")

    if args.prototype_uuid:
        try:
            env = await ctx.client.get_json(
                f"/prototype/datasets/{args.prototype_uuid}",
                token=ctx.token,
                stats=ctx.stats,
                cache="detail",
            )
        except NeonApiError as exc:
            raise api_error(
                exc, entity="prototype dataset", identifier=args.prototype_uuid
            ) from None
        raw = env.data or {}
        doi_url = (raw.get("doi") or {}).get("url")
        title = str(raw.get("projectTitle") or "")
        version = str(raw.get("version") or "")
        text = Template(templates.prototype).substitute(
            projectTitle=title,
            version=version,
            doiUrl=doi_url or "(no DOI)",
            uuid=args.prototype_uuid,
            accessedOn=accessed,
        )
        year = str(raw.get("dateUploaded") or "")[:4] or str(datetime.now(UTC).year)
        bib = _bibtex(
            f"neon_prototype_{args.prototype_uuid[:8]}",
            title=f"{title}, version {version}",
            year=year,
            doi=bare_doi(doi_url),
            url=doi_url or f"{PORTAL}/prototype-datasets/{args.prototype_uuid}",
            accessed=accessed,
        )
        return Citation(
            prototype_uuid=args.prototype_uuid,
            project_title=title,
            doi=bare_doi(doi_url),
            doi_url=doi_url,
            accessed_on=accessed,
            citation_text=text if args.format != "bibtex" else None,
            bibtex=bib if args.format != "text" else None,
            notes=notes,
            next_steps=[f"neon_get_prototype_dataset(uuid='{args.prototype_uuid}') for files"],
            source=source(ctx),
        )

    code, res = await resolve_product(args.product or "", ctx)
    index = await ctx.catalog.products(token=ctx.token, stats=ctx.stats)
    rec = index.by_code(code)
    if rec is None:
        raise ToolError(
            "not_found",
            f"product {code!r} is not in the NEON catalog.",
            details={"entity": "product", "identifier": code},
        )
    name = rec.product_name
    resolved = [res] if res else []
    if args.provisional:
        text = Template(templates.provisional).substitute(
            productName=name, productCode=code, accessedOn=accessed
        )
        bib = _bibtex(
            f"neon_{code.replace('.', '_').lower()}_provisional",
            title=f"{name} ({code}), provisional data",
            year=str((args.accessed_on or datetime.now(UTC).date()).year),
            doi=None,
            url=f"{PORTAL}/data-products/{code}",
            accessed=accessed,
        )
        notes.append(
            "Provisional data have no DOI and may change; archive the exact files you used."
        )
        return Citation(
            product_code=code,
            product_name=name,
            provisional=True,
            accessed_on=accessed,
            citation_text=text if args.format != "bibtex" else None,
            bibtex=bib if args.format != "text" else None,
            resolved=resolved,
            notes=notes,
            next_steps=["Read neon://guide/citing-neon-data"],
            source=source(ctx),
        )

    with_doi = sorted((r for r in rec.releases if r.doi_url), key=lambda r: r.release)
    if args.release == "latest":
        if not with_doi:
            raise ToolError(
                "not_found",
                f"{code} has no release with a DOI yet (only provisional data).",
                details={"entity": "release", "identifier": "latest", "availableReleases": []},
                hint="Cite provisional data with provisional=true.",
            )
        chosen = with_doi[-1]
    else:
        tag = await _resolve_release(args.release, ctx)
        match = next((r for r in with_doi if r.release == tag), None)
        if match is None:
            raise ToolError(
                "not_found",
                f"{code} has no DOI in {tag}.",
                details={
                    "entity": "release",
                    "identifier": tag,
                    "availableReleases": [r.release for r in with_doi],
                },
            )
        chosen = match
    try:
        for rel in await ctx.catalog.releases(token=ctx.token, stats=ctx.stats):
            if rel.get("release") != chosen.release:
                continue
            listed = next(
                (p for p in rel.get("dataProducts") or [] if p.get("productCode") == code), None
            )
            listed_doi = listed.get("productDoi") if listed else None
            if isinstance(listed_doi, dict):
                listed_doi = listed_doi.get("url")
            if listed_doi and listed_doi != chosen.doi_url:
                notes.append(
                    f"The release record lists {listed_doi}; the product record lists {chosen.doi_url}."
                )
    except (NeonApiError, ToolError):
        notes.append("Could not cross-check the DOI against the release record.")
    text = Template(templates.released).substitute(
        productName=name,
        productCode=code,
        release=chosen.release,
        doiUrl=chosen.doi_url,
        accessedOn=accessed,
    )
    year = chosen.release.rsplit("-", 1)[-1]
    bib = _bibtex(
        f"neon_{code.replace('.', '_').lower()}_{chosen.release.lower().replace('-', '_')}",
        title=f"{name} ({code}), {chosen.release}",
        year=year,
        doi=bare_doi(chosen.doi_url),
        url=str(chosen.doi_url),
        accessed=accessed,
    )
    return Citation(
        product_code=code,
        product_name=name,
        release=chosen.release,
        doi=bare_doi(chosen.doi_url),
        doi_url=chosen.doi_url,
        accessed_on=accessed,
        citation_text=text if args.format != "bibtex" else None,
        bibtex=bib if args.format != "text" else None,
        resolved=resolved,
        notes=notes,
        next_steps=[
            "If you also used PROVISIONAL months, cite them separately with provisional=true"
        ],
        source=source(ctx),
    )
