"""Location projections: flattened hierarchies, summaries and detail."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import Field

from neon_mcp.models.common import NeonOutput, Page, ToolResultBase
from neon_mcp.projections.common import clip_text, null_list, paginate, properties_map

HISTORY_LIMIT = 100


class LocationSummary(NeonOutput):
    location_name: str
    location_type: str | None = None
    location_description: str | None = None
    site_code: str | None = None
    domain_code: str | None = None
    depth: int = 0
    parent: str | None = None
    is_field_site: bool | None = None
    location_decimal_latitude: float | None = None
    location_decimal_longitude: float | None = None
    location_elevation: float | None = None
    distance_km: float | None = None
    detail_error: dict[str, str] | None = None


class LocationRoot(NeonOutput):
    location_name: str
    location_type: str | None = None


class LocationList(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    roots: list[LocationRoot]
    location_type: str | None = None
    types_available: dict[str, int] | None = None
    hierarchy_nodes_scanned: int
    items: list[LocationSummary]
    page: Page


class ParentRef(NeonOutput):
    location_name: str
    location_type: str | None = None


class HistoryEntry(NeonOutput):
    current: bool | None = None
    location_start_date: str | None = None
    location_end_date: str | None = None
    location_decimal_latitude: float | None = None
    location_decimal_longitude: float | None = None
    location_elevation: float | None = None
    location_utm_easting: float | None = None
    location_utm_northing: float | None = None
    location_utm_zone: int | None = None
    location_utm_hemisphere: str | None = None
    alpha_orientation: float | None = None
    beta_orientation: float | None = None
    gamma_orientation: float | None = None
    x_offset: float | None = None
    y_offset: float | None = None
    z_offset: float | None = None
    location_properties: dict[str, Any] = Field(default_factory=dict)


class LocationDetail(ToolResultBase):
    budget_list: ClassVar[str | None] = "children"
    budget_page: ClassVar[str] = "children_page"

    location_name: str
    location_description: str | None = None
    location_type: str | None = None
    domain_code: str | None = None
    site_code: str | None = None
    location_decimal_latitude: float | None = None
    location_decimal_longitude: float | None = None
    location_elevation: float | None = None
    location_utm_easting: float | None = None
    location_utm_northing: float | None = None
    location_utm_hemisphere: str | None = None
    location_utm_zone: int | None = None
    alpha_orientation: float | None = None
    beta_orientation: float | None = None
    gamma_orientation: float | None = None
    x_offset: float | None = None
    y_offset: float | None = None
    z_offset: float | None = None
    offset_location: dict[str, Any] | None = None
    active_periods: list[dict[str, Any]] = Field(default_factory=list)
    has_polygon: bool = False
    property_count: int = 0
    location_properties: dict[str, Any] | None = None
    location_properties_raw: list[dict[str, Any]] | None = None
    location_polygon: dict[str, Any] | None = None
    location_parent: str | None = None
    location_parent_url: str | None = None
    parent_chain: list[ParentRef] | None = None
    children_by_type: dict[str, int] | None = None
    children: list[LocationSummary] | None = None
    children_page: Page | None = None
    hierarchy_nodes_scanned: int | None = None
    location_history: list[HistoryEntry] | None = None
    history_truncated: bool = False


_SCALARS = (
    "location_name",
    "location_description",
    "location_type",
    "domain_code",
    "site_code",
    "location_decimal_latitude",
    "location_decimal_longitude",
    "location_elevation",
    "location_utm_easting",
    "location_utm_northing",
    "location_utm_hemisphere",
    "location_utm_zone",
    "alpha_orientation",
    "beta_orientation",
    "gamma_orientation",
    "x_offset",
    "y_offset",
    "z_offset",
)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def root_site(raw: Mapping[str, Any]) -> str | None:
    site = raw.get("siteCode")
    if site:
        return str(site)
    return str(raw.get("locationName")) if raw.get("locationType") == "SITE" else None


def flatten_hierarchy(
    raw: Mapping[str, Any], *, location_type: str | None, max_depth: int
) -> tuple[list[LocationSummary], dict[str, int], int]:
    """Depth-first flatten of ``locationChildHierarchy``; returns (items, typesAvailable, nodesScanned)."""
    items: list[LocationSummary] = []
    types: Counter[str] = Counter()
    scanned = 0
    site = root_site(raw)
    domain = raw.get("domainCode")
    wanted = location_type.lower() if location_type else None

    def visit(nodes: Sequence[Mapping[str, Any]] | None, depth: int, parent: str | None) -> None:
        nonlocal scanned
        for node in nodes or []:
            scanned += 1
            kind = node.get("locationType")
            types[str(kind)] += 1
            if depth <= max_depth and (wanted is None or str(kind or "").lower() == wanted):
                description, _ = clip_text(node.get("locationDescription"), 160)
                items.append(
                    LocationSummary(
                        location_name=str(node.get("locationName")),
                        location_type=kind,
                        location_description=description,
                        site_code=site,
                        domain_code=domain,
                        depth=depth,
                        parent=parent,
                    )
                )
            visit(node.get("locationChildHierarchy"), depth + 1, str(node.get("locationName")))

    visit(raw.get("locationChildHierarchy"), 1, str(raw.get("locationName")))
    return items, dict(sorted(types.items())), scanned


def parent_chain(raw: Mapping[str, Any]) -> list[ParentRef]:
    chain: list[ParentRef] = []
    node = raw.get("locationParentHierarchy")
    while isinstance(node, Mapping):
        chain.append(
            ParentRef(
                location_name=str(node.get("locationName")), location_type=node.get("locationType")
            )
        )
        node = node.get("locationParentHierarchy")
    return chain


def summary_from_record(
    raw: Mapping[str, Any], *, depth: int = 0, parent: str | None = None
) -> LocationSummary:
    description, _ = clip_text(raw.get("locationDescription"), 160)
    return LocationSummary(
        location_name=str(raw.get("locationName")),
        location_type=raw.get("locationType"),
        location_description=description,
        site_code=raw.get("siteCode"),
        domain_code=raw.get("domainCode"),
        depth=depth,
        parent=parent if parent is not None else raw.get("locationParent"),
        location_decimal_latitude=raw.get("locationDecimalLatitude"),
        location_decimal_longitude=raw.get("locationDecimalLongitude"),
        location_elevation=raw.get("locationElevation"),
    )


def merge_location_details(
    items: Sequence[LocationSummary], details: Sequence[Mapping[str, Any]]
) -> int:
    """Copy coordinates from batch lookups onto items (by name); returns how many were filled."""
    by_name = {str(d.get("locationName")): d for d in details}
    filled = 0
    for item in items:
        found = by_name.get(item.location_name)
        if found is None:
            continue
        if found.get("detailError"):
            item.detail_error = dict(found["detailError"])
            continue
        item.location_decimal_latitude = found.get("locationDecimalLatitude")
        item.location_decimal_longitude = found.get("locationDecimalLongitude")
        item.location_elevation = found.get("locationElevation")
        item.site_code = item.site_code or found.get("siteCode")
        item.domain_code = item.domain_code or found.get("domainCode")
        if item.location_type is None:
            item.location_type = found.get("locationType")
        filled += 1
    return filled


def _history(raw: Mapping[str, Any]) -> tuple[list[HistoryEntry], bool]:
    entries = null_list(raw.get("locationHistory"))
    out = []
    for h in entries[:HISTORY_LIMIT]:
        props, _ = properties_map(h.get("locationProperties"))
        fields = {
            name: h.get(_camel(name))
            for name in HistoryEntry.model_fields
            if name != "location_properties"
        }
        out.append(HistoryEntry(**fields, location_properties=props))
    return out, len(entries) > HISTORY_LIMIT


def project_location_detail(
    raw: Mapping[str, Any],
    *,
    include: frozenset[str],
    location_type: str | None,
    children_offset: int,
    children_limit: int,
    hierarchy_max_depth: int,
) -> LocationDetail:
    fields: dict[str, Any] = {name: raw.get(_camel(name)) for name in _SCALARS}
    fields["location_name"] = str(raw.get("locationName"))
    props = null_list(raw.get("locationProperties"))
    detail = LocationDetail(
        **fields,
        offset_location=raw.get("offsetLocation"),
        active_periods=[dict(p) for p in null_list(raw.get("activePeriods"))],
        has_polygon=bool(raw.get("locationPolygon")),
        property_count=len(props),
        location_parent=raw.get("locationParent"),
        location_parent_url=raw.get("locationParentUrl"),
    )
    if "properties" in include:
        detail.location_properties, detail.location_properties_raw = properties_map(props)
    if "polygon" in include and raw.get("locationPolygon"):
        detail.location_polygon = dict(raw["locationPolygon"])
    if "hierarchy" in include:
        detail.parent_chain = parent_chain(raw)
    if "children" in include:
        if raw.get("locationChildHierarchy") is not None:
            children, types, scanned = flatten_hierarchy(
                raw, location_type=location_type, max_depth=hierarchy_max_depth
            )
            detail.children_by_type = types if location_type is None else None
            detail.hierarchy_nodes_scanned = scanned
        else:
            children = [
                LocationSummary(location_name=str(name), depth=1, parent=detail.location_name)
                for name in null_list(raw.get("locationChildren"))
            ]
        detail.children, detail.children_page = paginate(
            children, offset=children_offset, limit=children_limit
        )
    if "history" in include:
        detail.location_history, detail.history_truncated = _history(raw)
    return detail
