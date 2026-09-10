"""``neon_get_document``: metadata and (optionally) text of NEON documents (ATBDs, protocols)."""

from __future__ import annotations

import io
import re
from typing import Any

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import NeonInput, SpecNumber
from neon_mcp.neon.resolve import resolve_product
from neon_mcp.projections.documents import Document
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, source

_SPEC_URL_RE = re.compile(r"/documents/(NEON\.DOC\.\d{6}(?:v[A-Z]{1,2})?)")
_PAGES_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


class GetDocumentIn(NeonInput):
    spec_number: SpecNumber | None = Field(
        None, description="Document number, e.g. NEON.DOC.000780vD."
    )
    url: str | None = Field(
        None, description="A https://data.neonscience.org/api/v0/documents/... URL."
    )
    product: str | None = Field(
        None, description="Check the document belongs to this product (code or name)."
    )
    extract_text: bool = Field(
        False, description="Extract the text (PDF via pypdf; needs neon-mcp[pdf])."
    )
    max_chars: int = Field(20_000, ge=500, le=100_000)
    char_offset: int = Field(0, ge=0)
    pages: str | None = Field(None, description="PDF pages to extract, e.g. '1-5' or '3'.")

    @model_validator(mode="after")
    def _one(self) -> GetDocumentIn:
        if (self.spec_number is None) == (self.url is None):
            raise ValueError("pass exactly one of spec_number or url")
        if self.pages is not None and not _PAGES_RE.match(self.pages):
            raise ValueError("pages must look like '3' or '1-5'")
        return self


def _page_range(pages: str | None, count: int) -> range:
    if not pages:
        return range(count)
    m = _PAGES_RE.match(pages)
    assert m is not None  # noqa: S101 - validated on input
    first = max(int(m.group(1)), 1)
    last = min(int(m.group(2) or first), count)
    return range(first - 1, max(last, first - 1))


def _pdf_text(blob: bytes, pages: str | None) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ToolError(
            "feature_unavailable",
            "Text extraction needs pypdf.",
            hint='pip install "neon-mcp[pdf]"',
        ) from None
    reader = PdfReader(io.BytesIO(blob))
    count = len(reader.pages)
    text = "\n\n".join(
        (reader.pages[i].extract_text() or "").strip() for i in _page_range(pages, count)
    )
    return text, count


@register_tool(
    "neon_get_document",
    title="Get a NEON document",
    description=(
        "Metadata of a NEON document (ATBD, protocol, user guide) by spec number or documents URL: type, "
        "size, file name, description and the products that reference it; optionally its text, extracted "
        "in memory and paged by character offset. No token. Next: page through text with char_offset, or "
        "call neon_download_files(spec_number=...) on stdio."
    ),
    input_model=GetDocumentIn,
    output_model=Document,
    surface="documents",
    endpoints=["GET /documents/{specNumber}"],
)
async def neon_get_document(args: GetDocumentIn, ctx: ToolContext) -> Document:
    spec = args.spec_number
    if spec is None:
        url = args.url or ""
        match = _SPEC_URL_RE.search(url)
        if not url.startswith(ctx.client.base_url + "/documents/") or not match:
            raise ToolError(
                "invalid_argument", f"url must start with {ctx.client.base_url}/documents/."
            )
        spec = match.group(1)
    path = f"/documents/{spec}"
    try:
        info = await ctx.client.head(path, token=None, stats=ctx.stats)
    except NeonApiError as exc:
        raise api_error(exc, entity="document", identifier=spec) from None
    notes: list[str] = []
    index = await ctx.catalog.products(token=ctx.token, stats=ctx.stats)
    ref, products = index.spec_lookup(spec)
    if args.product:
        code, _ = await resolve_product(args.product, ctx)
        if code not in products:
            notes.append(f"{spec} is not listed among {code}'s documents.")
    doc = Document(
        spec_number=spec,
        url=ctx.client.url_for(path),
        content_type=info.content_type,
        size=info.content_length,
        filename=info.filename,
        spec_description=ref.description if ref else None,
        spec_type=ref.spec_type if ref else None,
        referenced_by_products=products,
    )
    if args.extract_text:
        limit = ctx.config.limits.max_document_bytes
        if info.content_length and info.content_length > limit:
            raise ToolError(
                "result_too_large",
                f"{spec} is {info.content_length} bytes; text extraction is limited to {limit}.",
                hint="Download it with neon_download_files instead.",
            )
        key = f"text:{spec}:{args.pages or '*'}"
        cached: Any = ctx.client.cache.peek("documents", key)
        if cached is None:
            blob = await ctx.client.fetch_bytes(path, token=None, max_bytes=limit, stats=ctx.stats)
            if (info.content_type or "").endswith("pdf") or blob[:5] == b"%PDF-":
                cached = _pdf_text(blob, args.pages)
            elif (info.content_type or "").startswith("text/"):
                cached = (blob.decode("utf-8", "replace"), None)
            else:
                cached = ("", None)
                notes.append(
                    f"Text extraction supports PDF and text documents, not {info.content_type}."
                )
            ctx.client.cache.put("documents", key, cached, ttl_s=ctx.config.cache.ttl_s.documents)
        text, page_count = cached
        chunk = text[args.char_offset : args.char_offset + args.max_chars]
        end = args.char_offset + len(chunk)
        doc.text = chunk
        doc.chars_total = len(text)
        doc.page_count = page_count
        doc.pages = args.pages
        doc.text_truncated = end < len(text)
        doc.next_char_offset = end if doc.text_truncated else None
    steps = []
    if doc.next_char_offset is not None:
        steps.append(f"Repeat with char_offset={doc.next_char_offset} for more text")
    elif not args.extract_text:
        steps.append(f"neon_get_document(spec_number='{spec}', extract_text=True) for the text")
    if products:
        steps.append(f"neon_get_product(product='{products[0]}')")
    doc.notes, doc.next_steps, doc.source = notes, steps, source(ctx)
    return doc
