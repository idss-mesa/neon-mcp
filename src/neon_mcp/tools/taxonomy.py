"""``neon_search_taxonomy``: NEON's taxon lists by type code or rank."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError
from neon_mcp.models.common import NeonInput, Page, TaxonTypeCode
from neon_mcp.projections.taxonomy import TaxonPage, offset_from_next, project_taxon
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source

VERBOSE_MAX = 100
FALLBACK_LIMIT = 100
RANKS = ("kingdom", "phylum", "division", "class_", "order", "family", "genus", "scientific_name")
WIRE = {"class_": "class", "scientific_name": "scientificname"}


class SearchTaxonomyIn(NeonInput):
    taxon_type_code: TaxonTypeCode | None = Field(
        None,
        description="ALGAE, BEETLE, BIRD, FISH, HERPETOLOGY, MACROINVERTEBRATE, MOSQUITO, MOSQUITO_PATHOGENS, "
        "PLANT, SMALL_MAMMAL or TICK. Cannot be combined with a rank filter.",
    )
    kingdom: str | None = None
    phylum: str | None = None
    division: str | None = None
    class_: str | None = Field(
        None, validation_alias=AliasChoices("class_", "class"), description="Class (e.g. Aves)."
    )
    order: str | None = None
    family: str | None = None
    genus: str | None = Field(None, description="Genus, e.g. Quercus.")
    scientific_name: str | None = Field(
        None,
        validation_alias=AliasChoices("scientific_name", "scientificName", "scientificname"),
        description="Exact scientific name (NEON matches exactly; a genus fallback runs when nothing matches).",
    )
    verbose: bool = Field(
        False, description="All ranks and extra fields (nulls dropped); limit capped at 100."
    )
    fuzzy_genus_fallback: bool = Field(
        True, description="Retry an unmatched 'Genus species' by genus and filter."
    )
    limit: int = Field(25, ge=1, le=500)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _filters(self) -> SearchTaxonomyIn:
        ranks = [r for r in RANKS if getattr(self, r)]
        if self.taxon_type_code and ranks:
            raise ValueError(
                "taxon_type_code cannot be combined with rank filters (NEON: 'Taxon type code and taxon rank "
                "parameters must not both be specified')"
            )
        if not self.taxon_type_code and not ranks:
            raise ValueError("pass taxon_type_code or at least one rank filter")
        return self


@register_tool(
    "neon_search_taxonomy",
    title="Search NEON taxonomy",
    description=(
        "NEON's taxonomy lists, paged: every taxon of a type (BIRD, PLANT, SMALL_MAMMAL, ...) or taxa by rank "
        "(kingdom ... genus) or exact scientific name with a genus fallback. Rows keep NEON's Darwin Core "
        "keys (dwc:scientificName, dwc:vernacularName, ...). No token. Next: follow page.nextOffset, or "
        "call neon_search_products for data about the taxa."
    ),
    input_model=SearchTaxonomyIn,
    output_model=TaxonPage,
    surface="taxonomy",
    endpoints=["GET /taxonomy"],
)
async def neon_search_taxonomy(args: SearchTaxonomyIn, ctx: ToolContext) -> TaxonPage:
    notes: list[str] = []
    limit = args.limit
    if args.verbose and limit > VERBOSE_MAX:
        limit = VERBOSE_MAX
        notes.append(f"limit capped at {VERBOSE_MAX} for verbose rows.")
    filters: dict[str, Any] = {"taxonTypeCode": args.taxon_type_code}
    for rank in RANKS:
        value = getattr(args, rank)
        if value:
            filters[WIRE.get(rank, rank)] = value

    async def fetch(params: dict[str, Any], lim: int) -> dict[str, Any]:
        try:
            env = await ctx.client.get_json(
                "/taxonomy",
                {**params, "verbose": args.verbose, "offset": args.offset, "limit": lim},
                token=ctx.token,
                stats=ctx.stats,
                cache="taxonomy",
            )
        except NeonApiError as exc:
            raise api_error(
                exc, entity="taxon", identifier=str({k: v for k, v in params.items() if v})
            ) from None
        return dict(env.data or {})

    body = await fetch(filters, limit)
    rows = list(body.get("data") or [])
    fallback = False
    name = args.scientific_name
    if not rows and name and " " in name.strip() and args.fuzzy_genus_fallback and args.offset == 0:
        genus = name.strip().split()[0]
        body = await fetch({"genus": genus}, max(limit, FALLBACK_LIMIT))
        prefix = name.strip().lower()
        rows = [
            r
            for r in body.get("data") or []
            if str(r.get("dwc:scientificName", "")).lower().startswith(prefix)
        ]
        fallback = True
        notes.append(
            f"No exact match for {name!r}; showing genus {genus} names that start with it."
        )
        body = {"count": len(rows), "total": len(rows), "next": None}
    items = [project_taxon(r, verbose=args.verbose) for r in rows[:limit]]
    next_offset = offset_from_next(body.get("next"))
    total = body.get("total")
    page = Page(
        total=total if isinstance(total, int) else None,
        returned=len(items),
        offset=args.offset,
        limit=limit,
        truncated=next_offset is not None,
        next_offset=next_offset,
        truncated_reason="limit" if next_offset is not None else None,
    )
    steps = (
        [f"Repeat with offset={next_offset} for the next {limit} taxa"]
        if next_offset is not None
        else []
    )
    if not items:
        steps.append("Try a rank filter (genus=..., family=...) or taxon_type_code")
    steps.append("neon_search_products(query=<organism group>) for data products about these taxa")
    return TaxonPage(
        items=items,
        page=page,
        filters={k: v for k, v in filters.items() if v},
        fuzzy_fallback_used=fallback,
        notes=notes,
        next_steps=steps,
        source=source(ctx),
    )
