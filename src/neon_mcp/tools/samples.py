"""``neon_list_sample_classes`` and ``neon_get_sample`` (custody chain; token required).

``neon_get_sample`` is the one tool that uses MRTR: a sample tag can belong to
several sample classes, and when the caller did not name one, a client that
supports elicitation is asked to pick from the verifiable candidate list (the
public ``/samples/classes`` endpoint); other clients get ``ambiguous_input``.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import InputRequired, NeonApiError, ToolError
from neon_mcp.models.common import NeonInput
from neon_mcp.projections.common import paginate
from neon_mcp.projections.samples import (
    SampleClass,
    SampleClassList,
    SampleViews,
    project_sample_view,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source

ELICIT_KEY = "sample_class"
MAX_CHOICES = 8


class ListSampleClassesIn(NeonInput):
    sample_tag: str | None = Field(None, description="List the classes this sample tag belongs to.")
    query: str | None = Field(None, description="Substring filter on class key or description.")
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


async def _classes_for_tag(tag: str, ctx: ToolContext) -> list[str] | None:
    """Classes of a tag; ``None`` when NEON reports none (404)."""
    try:
        env = await ctx.client.get_json(
            "/samples/classes",
            {"sampleTag": tag},
            token=ctx.token,
            stats=ctx.stats,
            cache="samples_classes",
        )
    except NeonApiError as exc:
        if exc.status == 404 or (exc.status == 400 and "no sample classes" in exc.detail.lower()):
            return None
        raise
    return [str(c) for c in (env.data or {}).get("sampleClasses") or []]


@register_tool(
    "neon_list_sample_classes",
    title="List NEON sample classes",
    description=(
        "NEON's supported sample classes (e.g. bet_IDandpinning_in.individualID) with descriptions, filterable "
        "by text, or the classes one sample tag belongs to. No token. Next: call neon_get_sample with a tag "
        "and class, a sample UUID, a barcode or an archive GUID."
    ),
    input_model=ListSampleClassesIn,
    output_model=SampleClassList,
    surface="samples",
    endpoints=["GET /samples/supportedClasses", "GET /samples/classes"],
)
async def neon_list_sample_classes(args: ListSampleClassesIn, ctx: ToolContext) -> SampleClassList:
    notes: list[str] = []
    if args.sample_tag:
        classes = await _classes_for_tag(args.sample_tag, ctx)
        if classes is None:
            notes.append(f"NEON has no sample classes for tag {args.sample_tag!r}.")
            classes = []
        items = [SampleClass(sample_class=c) for c in classes]
        endpoint = "classes"
    else:
        entries = await ctx.catalog.sample_classes(token=ctx.token, stats=ctx.stats)
        items = [
            SampleClass(sample_class=str(e.get("key")), description=e.get("value")) for e in entries
        ]
        endpoint = "supportedClasses"
    if args.query:
        needle = args.query.lower()
        items = [
            i
            for i in items
            if needle in i.sample_class.lower() or needle in (i.description or "").lower()
        ]
    items.sort(key=lambda i: i.sample_class)
    page_items, page = paginate(items, offset=args.offset, limit=args.limit)
    steps = []
    if page_items and args.sample_tag:
        steps.append(
            f"neon_get_sample(sample_tag='{args.sample_tag}', sample_class='{page_items[0].sample_class}')"
        )
    elif page_items:
        steps.append("neon_get_sample(sample_tag=..., sample_class=...) needs a NEON API token")
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more classes")
    return SampleClassList(
        sample_tag=args.sample_tag,
        items=page_items,
        page=page,
        source_endpoint=endpoint,
        notes=notes,
        next_steps=steps,
        source=source(ctx),
    )


class GetSampleIn(NeonInput):
    sample_tag: str | None = Field(
        None, description="Sample tag (use with sample_class when it is ambiguous)."
    )
    sample_class: str | None = Field(
        None, description="Sample class of the tag, e.g. bet_IDandpinning_in.individualID."
    )
    sample_uuid: str | None = Field(None, description="Sample UUID.")
    barcode: str | None = Field(None, description="Sample barcode.")
    archive_guid: str | None = Field(None, description="Biorepository archive GUID.")
    degree: int | None = Field(
        None, ge=1, le=5, description="Also return relatives up to this many degrees away."
    )
    include_events: bool = Field(
        True, description="Include custody events (field entries folded into objects)."
    )
    events_limit: int = Field(50, ge=1, le=500)
    fields: list[str] | None = Field(None, description="Keep only these smsKey fields in events.")
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _one_mode(self) -> GetSampleIn:
        modes = [self.sample_tag, self.sample_uuid, self.barcode, self.archive_guid]
        if sum(1 for m in modes if m) != 1:
            raise ValueError("pass exactly one of sample_tag, sample_uuid, barcode or archive_guid")
        if self.sample_class and not self.sample_tag:
            raise ValueError("sample_class goes with sample_tag")
        return self


def _elicited_class(ctx: ToolContext, candidates: list[str]) -> str | None:
    if ctx.elicited is None:
        return None
    answer: Any = ctx.elicited.responses.get(ELICIT_KEY)
    if not isinstance(answer, dict):
        raise ToolError("invalid_argument", "The sample_class answer is missing.")
    if answer.get("action", "accept") != "accept":
        raise ToolError("invalid_argument", "Sample class selection was declined or cancelled.")
    content = answer.get("content") or {}
    choice = content.get("choice") if isinstance(content, dict) else None
    if choice not in candidates:
        raise ToolError(
            "invalid_argument",
            "The chosen sample class is no longer valid for this tag; call again.",
            details={"candidates": candidates},
        )
    return str(choice)


@register_tool(
    "neon_get_sample",
    title="Get a NEON sample",
    description=(
        "A physical sample's custody chain (NEON API token required): identifiers, events with their field "
        "values, parents and children; degree=N adds relatives N steps away. Identify it by tag (+class), "
        "UUID, barcode or archive GUID; an ambiguous tag asks which class (MRTR) or lists candidates. "
        "Next: follow parent or child identifiers with another neon_get_sample call."
    ),
    input_model=GetSampleIn,
    output_model=SampleViews,
    surface="samples",
    endpoints=["GET /samples/view", "GET /samples/download", "GET /samples/classes"],
    requires_token=True,
    supports_mrtr=True,
)
async def neon_get_sample(args: GetSampleIn, ctx: ToolContext) -> SampleViews:
    identifier: dict[str, str]
    params: dict[str, Any]
    notes: list[str] = []
    if args.sample_tag:
        sample_class = args.sample_class
        if sample_class is None:
            classes = await _classes_for_tag(args.sample_tag, ctx)
            if not classes:
                raise ToolError(
                    "not_found",
                    f"No sample classes exist for tag {args.sample_tag!r}.",
                    details={"entity": "sample", "identifier": args.sample_tag},
                )
            if len(classes) == 1:
                sample_class = classes[0]
            else:
                chosen = _elicited_class(ctx, classes)
                if chosen is not None:
                    sample_class = chosen
                elif ctx.elicitation_supported:
                    choices = classes[:MAX_CHOICES]
                    raise InputRequired(
                        key=ELICIT_KEY,
                        message=f"Sample tag {args.sample_tag} belongs to several classes; which one? "
                        + "; ".join(choices),
                        requested_schema={
                            "type": "object",
                            "properties": {
                                "choice": {
                                    "type": "string",
                                    "title": "sample_class",
                                    "enum": choices,
                                }
                            },
                            "required": ["choice"],
                        },
                        state={
                            "field": ELICIT_KEY,
                            "candidates": classes,
                            "sampleTag": args.sample_tag,
                        },
                    )
                else:
                    raise ToolError(
                        "ambiguous_input",
                        f"Sample tag {args.sample_tag!r} belongs to {len(classes)} classes; pass sample_class.",
                        details={
                            "field": "sample_class",
                            "input": args.sample_tag,
                            "candidates": [{"code": c, "label": c} for c in classes[:MAX_CHOICES]],
                        },
                    )
            notes.append(f"sample_class resolved to {sample_class}.")
        params = {"sampleTag": args.sample_tag, "sampleClass": sample_class}
        identifier = {
            "mode": "sample_tag",
            "value": args.sample_tag,
            "sampleClass": str(sample_class),
        }
    elif args.sample_uuid:
        params, identifier = (
            {"sampleUuid": args.sample_uuid},
            {"mode": "sample_uuid", "value": args.sample_uuid},
        )
    elif args.barcode:
        params, identifier = {"barcode": args.barcode}, {"mode": "barcode", "value": args.barcode}
    else:
        params = {"archiveGuid": args.archive_guid}
        identifier = {"mode": "archive_guid", "value": str(args.archive_guid)}
    path = "/samples/view"
    if args.degree:
        path = "/samples/download"
        params["degree"] = args.degree
    try:
        env = await ctx.client.get_json(
            path, params, token=ctx.token, stats=ctx.stats, cache="samples_view"
        )
    except NeonApiError as exc:
        raise api_error(exc, entity="sample", identifier=identifier["value"]) from None
    data = env.data or {}
    raw_views = data.get("sampleViews") or data.get("views") or []
    wanted = frozenset(args.fields) if args.fields else None
    views = [
        project_sample_view(
            v, include_events=args.include_events, events_limit=args.events_limit, fields=wanted
        )
        for v in raw_views
    ]
    page_items, page = paginate(views, offset=args.offset, limit=args.limit)
    steps: list[str] = []
    for view in page_items:
        for parent in view.parent_sample_identifiers[:1]:
            if parent.sample_uuid:
                steps.append(
                    f"neon_get_sample(sample_uuid='{parent.sample_uuid}') for the parent sample"
                )
        for child in view.child_sample_identifiers[:1]:
            if child.sample_uuid:
                steps.append(
                    f"neon_get_sample(sample_uuid='{child.sample_uuid}') for a child sample"
                )
    if page.next_offset is not None:
        steps.append(f"Repeat with offset={page.next_offset} for more views")
    if not steps:
        steps.append("neon_list_sample_classes(query=...) to explore other sample classes")
    return SampleViews(
        items=page_items,
        degree=args.degree,
        identifier=identifier,
        page=page,
        notes=notes,
        next_steps=steps,
        source=source(ctx),
    )
