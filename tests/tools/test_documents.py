from __future__ import annotations

import builtins
from typing import Any

import pytest

from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok
from tests.pdfgen import make_pdf

SPEC = "NEON.DOC.000780vD"
HEAD = Reply(
    content=b"",
    content_type="application/pdf",
    headers={
        "content-length": "715529",
        "content-disposition": f'attachment; filename="{SPEC}.pdf"',
    },
)


def pdf_routes(router: FixtureRouter, pages: list[str]) -> bytes:
    blob = make_pdf(pages)
    router.add(
        Route(
            "HEAD",
            f"/documents/{SPEC}",
            Reply(
                content=b"",
                content_type="application/pdf",
                headers={"content-length": str(len(blob))},
            ),
        ),
        Route("GET", f"/documents/{SPEC}", Reply(content=blob, content_type="application/pdf")),
    )
    return blob


async def test_metadata(server: NeonServer, router: FixtureRouter) -> None:
    router.add(Route("HEAD", f"/documents/{SPEC}", HEAD))
    payload = await call_ok(server, "neon_get_document", {"spec_number": SPEC})
    assert (payload["contentType"], payload["size"], payload["filename"]) == (
        "application/pdf",
        715529,
        f"{SPEC}.pdf",
    )
    assert payload["referencedByProducts"] == ["DP1.00001.001"]
    assert payload["specDescription"].startswith("NEON Algorithm Theoretical Basis Document")
    assert payload["url"] == f"https://data.neonscience.org/api/v0/documents/{SPEC}"
    assert "extract_text=True" in payload["nextSteps"][0]
    via_url = await call_ok(
        server,
        "neon_get_document",
        {
            "url": f"https://data.neonscience.org/api/v0/documents/{SPEC}",
            "product": "DP1.10003.001",
        },
    )
    assert any("not listed" in n for n in via_url["notes"])
    await call_err(
        server, "neon_get_document", {"url": "https://example.org/x.pdf"}, "invalid_argument"
    )


async def test_text_extraction_and_paging(server: NeonServer, router: FixtureRouter) -> None:
    pdf_routes(router, ["Alpha page one " * 40, "Bravo page two " * 40])
    full = await call_ok(
        server, "neon_get_document", {"spec_number": SPEC, "extract_text": True, "max_chars": 500}
    )
    assert (
        full["pageCount"] == 2
        and full["text"].startswith("Alpha")
        and full["textTruncated"] is True
    )
    assert full["nextCharOffset"] == 500 and full["charsTotal"] > 1000
    rest = await call_ok(
        server,
        "neon_get_document",
        {"spec_number": SPEC, "extract_text": True, "char_offset": 500, "max_chars": 100_000},
    )
    assert rest["textTruncated"] is False and "Bravo" in rest["text"]
    assert len(router.calls_to(f"GET /documents/{SPEC}")) == 1  # text cached
    page2 = await call_ok(
        server, "neon_get_document", {"spec_number": SPEC, "extract_text": True, "pages": "2"}
    )
    assert page2["text"].startswith("Bravo") and page2["pages"] == "2"


async def test_extraction_limits_and_types(
    server: NeonServer, router: FixtureRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    router.add(Route("HEAD", f"/documents/{SPEC}", HEAD))
    server.config.limits.max_document_bytes = 1024
    await call_err(
        server, "neon_get_document", {"spec_number": SPEC, "extract_text": True}, "result_too_large"
    )
    server.config.limits.max_document_bytes = 25 * 1024 * 1024
    router.add(
        Route(
            "HEAD", "/documents/NEON.DOC.000001vA", Reply(content=b"", content_type="text/plain")
        ),
        Route(
            "GET",
            "/documents/NEON.DOC.000001vA",
            Reply(content=b"plain words", content_type="text/plain"),
        ),
        Route(
            "HEAD",
            "/documents/NEON.DOC.000002vA",
            Reply(content=b"", content_type="application/vnd.ms-excel"),
        ),
        Route(
            "GET",
            "/documents/NEON.DOC.000002vA",
            Reply(content=b"\x00\x01", content_type="application/vnd.ms-excel"),
        ),
    )
    text = await call_ok(
        server, "neon_get_document", {"spec_number": "NEON.DOC.000001vA", "extract_text": True}
    )
    assert text["text"] == "plain words"
    xls = await call_ok(
        server, "neon_get_document", {"spec_number": "NEON.DOC.000002vA", "extract_text": True}
    )
    assert xls["text"] == "" and any("supports PDF" in n for n in xls["notes"])
    pdf_routes(router, ["x"])
    real_import = builtins.__import__

    def no_pypdf(name: str, *a: Any, **kw: Any) -> Any:
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    err = await call_err(
        server,
        "neon_get_document",
        {"spec_number": SPEC, "extract_text": True, "pages": "1"},
        "feature_unavailable",
    )
    assert "neon-mcp[pdf]" in err["hint"]


async def test_missing_document(server: NeonServer, router: FixtureRouter) -> None:
    router.add(
        Route("HEAD", "/documents/NEON.DOC.999999vZ", Reply(status=404, content=b"")),
        Route(
            "GET",
            "/documents/NEON.DOC.999999vZ",
            Reply(status=404, json={"error": {"status": 404, "detail": "Not found"}}),
        ),
    )
    await call_err(server, "neon_get_document", {"spec_number": "NEON.DOC.999999vZ"}, "not_found")
    await call_err(server, "neon_get_document", {"spec_number": "BAD"}, "invalid_argument")
    await call_err(
        server, "neon_get_document", {"spec_number": SPEC, "pages": "x-y"}, "invalid_argument"
    )
