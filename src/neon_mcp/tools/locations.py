"""``neon_find_locations`` and ``neon_get_location``."""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import LocationName, NeonInput, Resolved
from neon_mcp.neon.resolve import resolve_sites
from neon_mcp.projections.common import haversine_km, paginate
from neon_mcp.projections.locations import (
    LocationDetail,
    LocationList,
    LocationRoot,
    LocationSummary,
    flatten_hierarchy,
    merge_location_details,
    project_location_detail,
    summary_from_record,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source

DOMAIN_RE = re.compile(r"^D(0[1-9]|1\d|20)$")
SITE_CODE_RE = re.compile(r"^[A-Za-z]{4}$")
BATCH = 50
MAX_HYDRATE = 500
VOCABULARIES = Path(__file__).resolve().parents[1] / "resources_static" / "vocabularies.json"


@lru_cache(maxsize=1)
def known_location_types() -> dict[str, str]:
    types = json.loads(VOCABULARIES.read_text(encoding="utf-8")).get("locationTypes", [])
    return {str(t).lower(): str(t) for t in types}


def normalize_location_type(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    return known_location_types().get(text.lower(), text)


def normalize_root(value: str) -> str:
    text = value.strip()
    upper = text.upper()
    if upper == "REALM" or DOMAIN_RE.match(upper) or SITE_CODE_RE.match(text):
        return upper
    return text


def needs_location_type(root: str) -> bool:
    return root == "REALM" or bool(DOMAIN_RE.match(root))


class FindLocationsIn(NeonInput):
    root: LocationName | None = Field(
        None,
        description="Walk the hierarchy under REALM, a domain (D01), a site (HARV) or any named location.",
    )
    site_codes: list[str] | None = Field(
        None,
        min_length=1,
        max_length=20,
        description="Walk these sites instead (codes or names, up to 20).",
    )
    location_type: str | None = Field(
        None,
        description="Keep only this type: TOWER, HUT, MEGAPIT, SOIL_PLOT, 'OS Plot - mam', ... (see "
        "neon://reference/vocabularies). Required under REALM or a domain; prunes the walk upstream.",
    )
    query: str | None = Field(None, description="Substring filter on name or description.")
    latitude: float | None = Field(
        None, ge=-90, le=90, description="With longitude: nearest first, within radius_km."
    )
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_km: float = Field(50.0, gt=0, le=5000)
    include_coordinates: bool = Field(
        True, description="Look up coordinates for the returned page (batched)."
    )
    max_depth: int = Field(6, ge=1, le=12, description="Deepest hierarchy level to return.")
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _one_root(self) -> FindLocationsIn:
        if (self.root is None) == (self.site_codes is None):
            raise ValueError("pass exactly one of root or site_codes")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("pass latitude and longitude together")
        return self


async def _hydrate(
    items: list[LocationSummary], ctx: ToolContext
) -> Literal["graphql", "rest"] | None:
    names = [i.location_name for i in items if i.location_decimal_latitude is None]
    via: Literal["graphql", "rest"] | None = None
    for start in range(0, len(names), BATCH):
        rows, via = await ctx.catalog.locations_batch(
            names[start : start + BATCH], token=ctx.token, stats=ctx.stats
        )
        merge_location_details(items, rows)
    return via


@register_tool(
    "neon_find_locations",
    title="Find NEON locations",
    description=(
        "Locations under a site, domain, REALM or named location, filtered by locationType (towers, huts, "
        "megapits, soil plots, observation plots, ...) or text, with coordinates and optional proximity. "
        "REALM and domain walks need location_type; site walks without it report typesAvailable. "
        "Next: call neon_get_location for one location's detail."
    ),
    input_model=FindLocationsIn,
    output_model=LocationList,
    surface="locations",
    endpoints=["GET /locations/{locationName}", "GET /locations/sites", "POST /graphql"],
)
async def neon_find_locations(args: FindLocationsIn, ctx: ToolContext) -> LocationList:
    ltype = normalize_location_type(args.location_type)
    resolved: list[Resolved] = []
    if args.root is not None:
        roots = [normalize_root(args.root)]
    else:
        roots, resolved = await resolve_sites(args.site_codes or [], ctx)
    if ltype is None and any(needs_location_type(r) for r in roots):
        raise ToolError(
            "invalid_argument",
            "Walking REALM or a domain requires location_type (the unfiltered hierarchy is enormous).",
            hint="Pick a type from neon://reference/vocabularies, e.g. location_type='SITE' or 'TOWER'.",
        )
    items: list[LocationSummary] = []
    types: Counter[str] = Counter()
    scanned = 0
    root_refs: list[LocationRoot] = []
    notes: list[str] = []

    if roots == ["REALM"] and ltype == "SITE":
        rows = await ctx.catalog.site_locations(token=ctx.token, stats=ctx.stats)
        field_sites = (await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)).codes()
        root_refs.append(LocationRoot(location_name="REALM", location_type="FIELD"))
        for row in rows:
            item = summary_from_record(row, depth=1, parent="REALM")
            item.is_field_site = str(row.get("siteCode") or row.get("locationName")) in field_sites
            items.append(item)
        scanned = len(rows)
    else:
        for root in roots:
            try:
                env = await ctx.client.get_json(
                    f"/locations/{root}",
                    {"hierarchy": "true", "locationType": ltype},
                    token=ctx.token,
                    stats=ctx.stats,
                    cache="locations",
                )
            except NeonApiError as exc:
                raise api_error(
                    exc,
                    entity="location",
                    identifier=root,
                    hint="Location names are case-sensitive; sites are 4-letter codes.",
                ) from None
            raw = env.data or {}
            root_refs.append(
                LocationRoot(
                    location_name=str(raw.get("locationName") or root),
                    location_type=raw.get("locationType"),
                )
            )
            found, kinds, count = flatten_hierarchy(
                raw, location_type=ltype, max_depth=args.max_depth
            )
            items.extend(found)
            types.update(kinds)
            scanned += count
        if ltype is None:
            notes.append(
                "Unfiltered walk: pass location_type to prune it (typesAvailable lists what was seen)."
            )

    unique: dict[str, LocationSummary] = {}
    for item in items:
        unique.setdefault(item.location_name, item)
    ordered = sorted(unique.values(), key=lambda i: i.location_name)
    if args.query:
        needle = args.query.lower()
        ordered = [
            i
            for i in ordered
            if needle in i.location_name.lower() or needle in (i.location_description or "").lower()
        ]

    if args.latitude is not None and args.longitude is not None:
        if len(ordered) > MAX_HYDRATE:
            raise ToolError(
                "query_too_large",
                f"{len(ordered)} locations match; proximity needs coordinates for "
                f"each (limit {MAX_HYDRATE}).",
                hint="Add location_type or query to narrow the set.",
            )
        await _hydrate(ordered, ctx)
        with_coords: list[LocationSummary] = []
        for item in ordered:
            lat, lon = item.location_decimal_latitude, item.location_decimal_longitude
            if lat is None or lon is None:
                continue
            item.distance_km = round(haversine_km(args.latitude, args.longitude, lat, lon), 2)
            with_coords.append(item)
        ordered = sorted(
            (i for i in with_coords if (i.distance_km or 0.0) <= args.radius_km),
            key=lambda i: (i.distance_km or 0.0, i.location_name),
        )
    page_items, page = paginate(ordered, offset=args.offset, limit=args.limit)
    if args.include_coordinates and args.latitude is None and page_items:
        await _hydrate(page_items, ctx)

    steps: list[str] = []
    if page_items:
        steps.append(
            f"neon_get_location(name='{page_items[0].location_name}', include=['properties', 'hierarchy'])"
        )
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more locations")
    if ltype is None and types:
        common = max(types.items(), key=lambda kv: kv[1])[0]
        steps.append(f"Narrow with location_type='{common}' (or another type in typesAvailable)")
    if args.site_codes and len(args.site_codes) == 20:
        notes.append("20 sites is the per-call maximum; batch further sites in another call.")
    return LocationList(
        roots=root_refs,
        location_type=ltype,
        types_available=dict(sorted(types.items())) if ltype is None and types else None,
        hierarchy_nodes_scanned=scanned,
        items=page_items,
        page=page,
        resolved=resolved,
        notes=notes,
        next_steps=steps,
        source=source(ctx),
    )


class GetLocationIn(NeonInput):
    name: LocationName = Field(
        description="Location name (case-sensitive), e.g. HARV, TOWER100450, D01."
    )
    include: list[Literal["properties", "hierarchy", "history", "children", "polygon", "all"]] = (
        Field(
            default_factory=lambda: ["properties"],  # type: ignore[arg-type]
            description="properties (default), hierarchy (parent chain), history, children (paged), polygon, all.",
        )
    )
    location_type: str | None = Field(
        None, description="Prune children to this type (required for REALM/domains)."
    )
    children_limit: int = Field(50, ge=1, le=500)
    children_offset: int = Field(0, ge=0)
    hierarchy_max_depth: int = Field(3, ge=1, le=12)


@register_tool(
    "neon_get_location",
    title="Get a NEON location",
    description=(
        "One named location in depth: coordinates, UTM, elevation, orientation and offsets, properties, "
        "active periods; optionally its parent chain, location history, polygon and paged children "
        "(pruned by location_type). Names are case-sensitive. Next: call neon_find_locations to list "
        "locations of a type under it."
    ),
    input_model=GetLocationIn,
    output_model=LocationDetail,
    surface="locations",
    endpoints=["GET /locations/{locationName}"],
)
async def neon_get_location(args: GetLocationIn, ctx: ToolContext) -> LocationDetail:
    name = normalize_root(args.name)
    ltype = normalize_location_type(args.location_type)
    include = (
        frozenset({"properties", "hierarchy", "history", "children", "polygon"})
        if "all" in args.include
        else frozenset(args.include)
    )
    walk = bool(include & {"hierarchy", "children"})
    if walk and "children" in include and ltype is None and needs_location_type(name):
        raise ToolError(
            "invalid_argument",
            "Children of REALM or a domain require location_type.",
            hint="Pick a type from neon://reference/vocabularies.",
        )
    params: dict[str, str | None] = {
        "history": "true" if "history" in include else None,
        "hierarchy": "true" if walk else None,
        "locationType": ltype,
    }
    try:
        env = await ctx.client.get_json(
            f"/locations/{name}", params, token=ctx.token, stats=ctx.stats, cache="locations"
        )
    except NeonApiError as exc:
        raise api_error(
            exc,
            entity="location",
            identifier=name,
            hint="Location names are case-sensitive; sites are 4-letter codes.",
        ) from None
    detail = project_location_detail(
        env.data or {},
        include=include,
        location_type=ltype,
        children_offset=args.children_offset,
        children_limit=args.children_limit,
        hierarchy_max_depth=args.hierarchy_max_depth,
    )
    notes: list[str] = []
    steps: list[str] = []
    if detail.children_by_type:
        notes.append("Children listed without a location_type filter; pass one to prune the walk.")
        common = max(detail.children_by_type.items(), key=lambda kv: kv[1])[0]
        steps.append(f"neon_find_locations(root='{name}', location_type='{common}')")
    if detail.children_page and detail.children_page.next_offset is not None:
        steps.append(
            f"Repeat with children_offset={detail.children_page.next_offset} for more children"
        )
    if detail.location_parent:
        steps.append(f"neon_get_location(name='{detail.location_parent}') for the parent")
    detail.notes = notes
    detail.next_steps = steps or [f"neon_find_locations(root='{name}', location_type='TOWER')"]
    detail.source = source(ctx)
    return detail
