"""Release and citation projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field

from neon_mcp.models.common import NeonOutput, Page, ToolResultBase
from neon_mcp.projections.common import clip_text, null_list
from neon_mcp.projections.products import ProductCore
from neon_mcp.projections.sites import SiteCore

DATA_POLICY_URL = "https://www.neonscience.org/data-samples/data-policies-citation"


class Artifact(NeonOutput):
    name: str | None = None
    type: str | None = None
    size: int | None = None
    md5: str | None = None
    url: str | None = None


class ReleaseSummary(NeonOutput):
    release: str
    uuid: str | None = None
    generation_date: str | None = None
    product_count: int
    artifacts: list[Artifact] = Field(default_factory=list)


class ReleaseList(ToolResultBase):
    items: list[ReleaseSummary]
    latest_release: str | None = None
    page: Page


class ReleaseProduct(NeonOutput):
    product_code: str
    product_name: str | None = None
    product_description: str | None = None
    product_doi: str | None = None


class ReleaseSite(NeonOutput):
    site_code: str
    site_name: str | None = None
    domain_code: str | None = None
    state_code: str | None = None


class ReleaseDetail(ToolResultBase):
    budget_list: ClassVar[str | None] = "data_products"
    budget_page: ClassVar[str] = "products_page"

    release: str
    uuid: str | None = None
    generation_date: str | None = None
    product_count: int
    artifacts: list[Artifact] | None = None
    data_products: list[ReleaseProduct] | None = None
    products_page: Page | None = None
    sites: list[ReleaseSite] | None = None
    product: ProductCore | None = None
    site: SiteCore | None = None


class Citation(ToolResultBase):
    product_code: str | None = None
    prototype_uuid: str | None = None
    product_name: str | None = None
    project_title: str | None = None
    release: str | None = None
    provisional: bool = False
    doi: str | None = Field(None, description="Bare DOI, e.g. 10.48443/v6hs-mx57.")
    doi_url: str | None = None
    accessed_on: str
    citation_text: str | None = None
    bibtex: str | None = None
    data_policy_url: str = DATA_POLICY_URL


def artifacts(raw: Mapping[str, Any], *, include_urls: bool) -> list[Artifact]:
    return [
        Artifact(
            name=a.get("name"),
            type=a.get("type"),
            size=a.get("size"),
            md5=a.get("md5"),
            url=a.get("url") if include_urls else None,
        )
        for a in null_list(raw.get("artifacts"))
    ]


def project_release_summary(
    raw: Mapping[str, Any], *, include_artifact_urls: bool
) -> ReleaseSummary:
    return ReleaseSummary(
        release=str(raw.get("release")),
        uuid=raw.get("uuid"),
        generation_date=raw.get("generationDate"),
        product_count=len(null_list(raw.get("dataProducts"))),
        artifacts=artifacts(raw, include_urls=include_artifact_urls),
    )


def release_products(raw: Mapping[str, Any], query: str | None) -> list[ReleaseProduct]:
    needle = (query or "").lower().strip()
    out = []
    for p in null_list(raw.get("dataProducts")):
        code = str(p.get("productCode") or "")
        name = p.get("productName")
        if needle and needle not in code.lower() and needle not in str(name or "").lower():
            continue
        description, _ = clip_text(p.get("productDescription"), 300)
        doi = p.get("productDoi")
        if isinstance(doi, Mapping):
            doi = doi.get("url")
        out.append(
            ReleaseProduct(
                product_code=code,
                product_name=name,
                product_description=description,
                product_doi=doi,
            )
        )
    return sorted(out, key=lambda p: p.product_code)


def bare_doi(url: str | None) -> str | None:
    if not url:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


CitationFormat = Literal["text", "bibtex", "all"]
