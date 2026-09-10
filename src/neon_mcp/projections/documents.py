"""Document metadata and extracted text."""

from __future__ import annotations

from pydantic import Field

from neon_mcp.models.common import ToolResultBase


class Document(ToolResultBase):
    spec_number: str
    url: str
    content_type: str | None = None
    size: int | None = None
    filename: str | None = None
    spec_description: str | None = None
    spec_type: str | None = None
    referenced_by_products: list[str] = Field(default_factory=list)
    text: str | None = None
    text_truncated: bool = False
    next_char_offset: int | None = None
    chars_total: int | None = None
    page_count: int | None = None
    pages: str | None = None
