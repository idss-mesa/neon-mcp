"""Sample custody projections (``/samples/view`` and ``/samples/download``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field

from neon_mcp.models.common import NeonOutput, Page, ToolResultBase
from neon_mcp.projections.common import null_list


class SampleIdentifier(NeonOutput):
    sample_uuid: str | None = None
    sample_tag: str | None = None
    sample_class: str | None = None
    barcode: str | None = None
    archive_guid: str | None = None


class SampleEvent(NeonOutput):
    ingest_table_name: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    fields_raw: list[dict[str, Any]] | None = Field(
        None, description="Present when a key repeats within the event."
    )


class SampleView(NeonOutput):
    sample_uuid: str | None = None
    sample_tag: str | None = None
    sample_class: str | None = None
    barcode: str | None = None
    archive_guid: str | None = None
    event_count: int = 0
    sample_events: list[SampleEvent] = Field(default_factory=list)
    events_truncated: bool = False
    parent_sample_identifiers: list[SampleIdentifier] = Field(default_factory=list)
    child_sample_identifiers: list[SampleIdentifier] = Field(default_factory=list)


class SampleViews(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    items: list[SampleView]
    degree: int | None = None
    identifier: dict[str, str]
    page: Page


class SampleClass(NeonOutput):
    sample_class: str
    description: str | None = None


class SampleClassList(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"

    sample_tag: str | None = None
    items: list[SampleClass]
    page: Page
    source_endpoint: Literal["classes", "supportedClasses"]


def _identifier(raw: Mapping[str, Any]) -> SampleIdentifier:
    return SampleIdentifier(
        sample_uuid=raw.get("sampleUuid"),
        sample_tag=raw.get("sampleTag"),
        sample_class=raw.get("sampleClass"),
        barcode=raw.get("barcode"),
        archive_guid=raw.get("archiveGuid"),
    )


def _event(raw: Mapping[str, Any], wanted: frozenset[str] | None) -> SampleEvent:
    folded: dict[str, Any] = {}
    duplicate = False
    entries = [
        e
        for e in null_list(raw.get("smsFieldEntries"))
        if wanted is None or e.get("smsKey") in wanted
    ]
    for entry in entries:
        key = str(entry.get("smsKey"))
        if key in folded:
            duplicate = True
        folded[key] = entry.get("smsValue")
    return SampleEvent(
        ingest_table_name=raw.get("ingestTableName"),
        fields=folded,
        fields_raw=[dict(e) for e in entries] if duplicate else None,
    )


def project_sample_view(
    raw: Mapping[str, Any],
    *,
    include_events: bool,
    events_limit: int,
    fields: frozenset[str] | None,
) -> SampleView:
    events = null_list(raw.get("sampleEvents"))
    return SampleView(
        sample_uuid=raw.get("sampleUuid"),
        sample_tag=raw.get("sampleTag"),
        sample_class=raw.get("sampleClass"),
        barcode=raw.get("barcode"),
        archive_guid=raw.get("archiveGuid"),
        event_count=len(events),
        sample_events=[_event(e, fields) for e in events[:events_limit]] if include_events else [],
        events_truncated=include_events and len(events) > events_limit,
        parent_sample_identifiers=[
            _identifier(p) for p in null_list(raw.get("parentSampleIdentifiers"))
        ],
        child_sample_identifiers=[
            _identifier(c) for c in null_list(raw.get("childSampleIdentifiers"))
        ],
    )
