"""``neon_graphql``: a guard-railed, read-only GraphQL escape hatch."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import ToolError
from neon_mcp.models.common import NeonInput, Source, ToolResultBase
from neon_mcp.neon.gql_guard import check_query, prune_to_budget
from neon_mcp.neon.gql_queries import INTROSPECT_ONE
from neon_mcp.registry import json_size, register_tool

SCHEMA_RESOURCE = "neon://reference/graphql-schema"
_ENVELOPE_MARGIN = 2_000


class GraphqlIn(NeonInput):
    query: str | None = Field(
        None,
        description="A read-only GraphQL query against https://data.neonscience.org/graphql "
        "(roots: products, product, filterProducts, sites, site, filterSites, location, "
        "locationHierarchy, findLocations, prototypeDatasets, prototypeDataset, one __type).",
    )
    introspect_type: str | None = Field(
        None,
        pattern=r"^[_A-Za-z][_0-9A-Za-z]*$",
        description="Instead of a query: describe one GraphQL type (e.g. Site, DataProductFilter).",
    )
    variables: dict[str, Any] | None = Field(None, description="GraphQL variables.")
    operation_name: str | None = Field(
        None, description="Operation to run when the document has several."
    )
    max_bytes: int = Field(
        50_000, ge=1_000, le=200_000, description="Response budget; larger lists are pruned."
    )

    @model_validator(mode="after")
    def _one_mode(self) -> GraphqlIn:
        if (self.query is None) == (self.introspect_type is None):
            raise ValueError("pass exactly one of query or introspect_type")
        return self


class GraphQLResult(ToolResultBase):
    data: Any = None
    errors: list[dict[str, Any]] | None = None
    bytes_total: int
    truncated: bool = False
    truncated_paths: list[str] = Field(default_factory=list)
    schema_hint: str = SCHEMA_RESOURCE


@register_tool(
    "neon_graphql",
    title="Run a NEON GraphQL query",
    description=(
        "Read-only GraphQL against NEON's public metadata endpoint for shapes the other tools do not "
        "cover. Guard rails: queries only, allow-listed root fields, depth <= 8, one __type/__schema, "
        "results pruned to max_bytes with truncatedPaths. No token is sent. Prefer the dedicated tools "
        "for products, sites and availability. Next: read neon://reference/graphql-schema for types."
    ),
    input_model=GraphqlIn,
    output_model=GraphQLResult,
    surface="graphql",
    endpoints=["POST /graphql"],
)
async def neon_graphql(args: GraphqlIn, ctx: ToolContext) -> GraphQLResult:
    limits = ctx.config.limits
    if args.introspect_type is not None:
        env = await ctx.client.graphql(
            INTROSPECT_ONE, {"name": args.introspect_type}, token=None, stats=ctx.stats
        )
    else:
        query = args.query or ""
        check_query(
            query, max_chars=limits.graphql_max_query_chars, max_depth=limits.graphql_max_depth
        )
        env = await ctx.client.graphql(
            query, args.variables, operation_name=args.operation_name, token=None, stats=ctx.stats
        )
    data = env.data.get("data")
    errors = env.data.get("errors")
    has_data = isinstance(data, dict) and any(v is not None for v in data.values())
    if errors and not has_data:
        if any(
            (e.get("extensions") or {}).get("classification") == "BadFaithIntrospection"
            for e in errors
        ):
            raise ToolError(
                "invalid_argument",
                "NEON allows a single __type or __schema per query.",
                details={"errors": errors[:5]},
            )
        if any(re.search(r"not\s+found", str(e.get("message", "")), re.I) for e in errors):
            raise ToolError(
                "not_found", str(errors[0].get("message")), details={"errors": errors[:5]}
            )
        raise ToolError(
            "graphql_error",
            "NEON rejected the GraphQL query.",
            details={"errors": errors[:5]},
            hint=f"Check field names in {SCHEMA_RESOURCE}.",
        )
    budget = min(args.max_bytes, limits.graphql_hard_max_response_bytes) - _ENVELOPE_MARGIN
    total = json_size(data)
    data, paths = prune_to_budget(data, max(budget, 500))
    notes = []
    if errors:
        notes.append(f"NEON returned {len(errors)} GraphQL error(s) alongside partial data.")
    steps = [f"Read {SCHEMA_RESOURCE} for root fields and input types"]
    if paths:
        steps.insert(
            0, "Select fewer fields or filter (filterProducts/filterSites) to avoid pruning"
        )
    return GraphQLResult(
        data=data,
        errors=errors[:20] if errors else None,
        bytes_total=total,
        truncated=bool(paths),
        truncated_paths=paths,
        notes=notes,
        next_steps=steps,
        source=Source(endpoints=["POST /graphql"], via="graphql", cached=False),
    )
