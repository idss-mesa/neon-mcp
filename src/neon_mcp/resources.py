"""MCP resources: static guides, derived references, and tool-backed templates."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mcp import types as t

from neon_mcp.errors import ToolError

if TYPE_CHECKING:
    from neon_mcp.context import ToolContext

STATIC_DIR = Path(__file__).parent / "resources_static"
META_RESOURCE_KIND = "io.neon-mcp/kind"
STATIC_TTL_MS = 86_400_000
DERIVED_TTL_MS = 3_600_000


@dataclass(frozen=True)
class ResourceContent:
    text: str
    mime_type: str
    ttl_ms: int
    kind: Literal["static", "derived"]


@dataclass(frozen=True)
class _Static:
    uri: str
    file: str
    mime_type: str
    title: str
    description: str


@dataclass(frozen=True)
class _Template:
    uri_template: str
    pattern: re.Pattern[str]
    tool: str
    argument: str
    title: str
    description: str
    extra_args: tuple[tuple[str, Any], ...] = ()


STATIC: tuple[_Static, ...] = (
    _Static(
        "neon://guide/agent-workflow",
        "agent-workflow.md",
        "text/markdown",
        "Agent workflow",
        "Five-call recipe from question to cited data, input rules and error remedies.",
    ),
    _Static(
        "neon://guide/api-token",
        "api-token.md",
        "text/markdown",
        "NEON API token",
        "Which endpoints need a token (since 2026-06), how to obtain it and pass it, rate limits.",
    ),
    _Static(
        "neon://guide/citing-neon-data",
        "citing-neon-data.md",
        "text/markdown",
        "Citing NEON data",
        "Data policy, released vs provisional citation wording, and the citation templates.",
    ),
    _Static(
        "neon://guide/product-code-anatomy",
        "product-code-anatomy.md",
        "text/markdown",
        "Product codes, files and releases",
        "Product-code levels, packages, file-name grammar (HOR/VER/TMI), releases and PROVISIONAL.",
    ),
    _Static(
        "neon://reference/vocabularies",
        "vocabularies.json",
        "application/json",
        "Vocabularies",
        "Valid filter values: themes, teams, domains, taxon types, location types, releases, file kinds.",
    ),
    _Static(
        "neon://reference/graphql-schema",
        "graphql-schema.md",
        "text/markdown",
        "GraphQL schema",
        "Root fields, input types and object fields of NEON's GraphQL endpoint for neon_graphql.",
    ),
)
DERIVED: tuple[tuple[str, str, str], ...] = (
    (
        "neon://reference/sites",
        "NEON field sites",
        "All 81 field sites: code, name, type, domain, state, latitude, longitude (~10 KB).",
    ),
    (
        "neon://reference/releases",
        "NEON data releases",
        "Every release with generation date and product count, plus the latest release tag.",
    ),
)
TEMPLATES: tuple[_Template, ...] = (
    _Template(
        "neon://products/{productCode}",
        re.compile(r"^neon://products/([^/?#]+)$"),
        "neon_get_product",
        "product",
        "NEON data product",
        "A data product's base record (neon_get_product payload).",
    ),
    _Template(
        "neon://sites/{siteCode}",
        re.compile(r"^neon://sites/([^/?#]+)$"),
        "neon_get_site",
        "site",
        "NEON field site",
        "A field site with its data products (neon_get_site payload).",
        (("include", ["products"]),),
    ),
    _Template(
        "neon://releases/{release}",
        re.compile(r"^neon://releases/([^/?#]+)$"),
        "neon_get_release",
        "release",
        "NEON data release",
        "A release with its products and DOIs (neon_get_release payload).",
    ),
)


def list_resources() -> list[t.Resource]:
    out = [
        t.Resource(
            name=s.uri.rsplit("/", 1)[-1],
            uri=s.uri,
            title=s.title,
            description=s.description,
            mime_type=s.mime_type,
            meta={META_RESOURCE_KIND: "static"},
        )
        for s in STATIC
    ]
    out.extend(
        t.Resource(
            name=uri.rsplit("/", 1)[-1],
            uri=uri,
            title=title,
            description=desc,
            mime_type="application/json",
            meta={META_RESOURCE_KIND: "derived"},
        )
        for uri, title, desc in DERIVED
    )
    return sorted(out, key=lambda r: str(r.uri))


def list_resource_templates() -> list[t.ResourceTemplate]:
    return [
        t.ResourceTemplate(
            name=tpl.tool.removeprefix("neon_get_"),
            uri_template=tpl.uri_template,
            title=tpl.title,
            description=tpl.description,
            mime_type="application/json",
        )
        for tpl in TEMPLATES
    ]


@lru_cache(maxsize=16)
def _static_text(file: str) -> str:
    return (STATIC_DIR / file).read_text(encoding="utf-8")


def _compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def known_uris() -> list[str]:
    return (
        [s.uri for s in STATIC] + [d[0] for d in DERIVED] + [tpl.uri_template for tpl in TEMPLATES]
    )


async def read_resource(uri: str, ctx: ToolContext, *, server: Any = None) -> ResourceContent:
    """Read one ``neon://`` resource; ``ToolError(not_found)`` with ``didYouMean`` otherwise."""
    del server
    for s in STATIC:
        if s.uri == uri:
            return ResourceContent(_static_text(s.file), s.mime_type, STATIC_TTL_MS, "static")
    if uri == "neon://reference/sites":
        index = await ctx.catalog.sites(token=ctx.token, stats=ctx.stats)
        rows = [
            {
                "siteCode": r.site_code,
                "siteName": r.site_name,
                "siteType": r.site_type,
                "domainCode": r.domain_code,
                "stateCode": r.state_code,
                "siteLatitude": r.latitude,
                "siteLongitude": r.longitude,
            }
            for r in index.records
        ]
        return ResourceContent(
            _compact({"sites": rows, "count": len(rows)}),
            "application/json",
            DERIVED_TTL_MS,
            "derived",
        )
    if uri == "neon://reference/releases":
        releases = await ctx.catalog.releases(token=ctx.token, stats=ctx.stats)
        rows = sorted(
            (
                {
                    "release": r.get("release"),
                    "generationDate": r.get("generationDate"),
                    "productCount": len(r.get("dataProducts") or []),
                }
                for r in releases
            ),
            key=lambda r: str(r["release"]),
            reverse=True,
        )
        latest = rows[0]["release"] if rows else None
        return ResourceContent(
            _compact({"releases": rows, "latestRelease": latest}),
            "application/json",
            DERIVED_TTL_MS,
            "derived",
        )
    for tpl in TEMPLATES:
        match = tpl.pattern.match(uri)
        if match:
            from neon_mcp.registry import get_tool, invoke

            args: dict[str, Any] = {tpl.argument: match.group(1), **dict(tpl.extra_args)}
            payload = await invoke(get_tool(tpl.tool), args, ctx)
            return ResourceContent(_compact(payload), "application/json", DERIVED_TTL_MS, "derived")
    raise ToolError(
        "not_found",
        f"Unknown resource {uri!r}.",
        details={
            "uri": uri,
            "didYouMean": difflib.get_close_matches(uri, known_uris(), n=3, cutoff=0.4),
        },
    )


# ---------------------------------------------------------------------------
# Citation templates (fenced blocks in citing-neon-data.md)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CitationTemplates:
    released: str
    provisional: str
    prototype: str
    bibtex: str


_FENCE_RE = re.compile(r"```([a-z-]+)\n(.*?)\n```", re.DOTALL)


@lru_cache(maxsize=1)
def citation_templates() -> CitationTemplates:
    blocks = {
        m.group(1): m.group(2).strip()
        for m in _FENCE_RE.finditer(_static_text("citing-neon-data.md"))
    }
    missing = {"citation-released", "citation-provisional", "citation-prototype", "bibtex"} - set(
        blocks
    )
    if missing:  # pragma: no cover - guarded by a unit test on the shipped file
        raise RuntimeError(f"citing-neon-data.md lacks template blocks: {sorted(missing)}")
    return CitationTemplates(
        released=blocks["citation-released"],
        provisional=blocks["citation-provisional"],
        prototype=blocks["citation-prototype"],
        bibtex=blocks["bibtex"],
    )
