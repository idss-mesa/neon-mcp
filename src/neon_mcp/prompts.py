"""MCP prompts: three task recipes that steer an agent through the tools."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from mcp import types as t

from neon_mcp.errors import ToolError


@dataclass(frozen=True)
class _Arg:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class _Prompt:
    name: str
    title: str
    description: str
    arguments: tuple[_Arg, ...]


PROMPTS: tuple[_Prompt, ...] = (
    _Prompt(
        "neon_cite_dataset",
        "Cite a NEON dataset",
        "Produce a NEON-format citation and BibTeX for a data product (and release).",
        (
            _Arg(
                "product", "Product code or name, e.g. DP1.10003.001 or 'breeding landbird'.", True
            ),
            _Arg("release", "Release tag such as RELEASE-2026 (default: latest with a DOI)."),
            _Arg("site_codes", "Comma-separated site codes the data came from (optional)."),
        ),
    ),
    _Prompt(
        "neon_find_data",
        "Find NEON data for a question",
        "Go from a research question to candidate NEON products, sites and months with availability.",
        (
            _Arg("question", "The research question in plain language.", True),
            _Arg("region", "Place, state, domain (D01-D20) or site to focus on."),
            _Arg("timeframe", "Months or years of interest, e.g. 2019-2023."),
            _Arg("organism_or_variable", "Organism group or measured variable."),
        ),
    ),
    _Prompt(
        "neon_plan_download",
        "Plan a NEON download",
        "Size, list and (on stdio) download NEON data files for product x sites x months, then cite them.",
        (
            _Arg("product", "Product code or name.", True),
            _Arg("sites", "Comma-separated site codes or names.", True),
            _Arg("start_month", "First month, YYYY-MM.", True),
            _Arg("end_month", "Last month, YYYY-MM (default: start_month)."),
            _Arg("package", "basic (default) or expanded."),
        ),
    ),
)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def list_prompts() -> list[t.Prompt]:
    return [
        t.Prompt(
            name=p.name,
            title=p.title,
            description=p.description,
            arguments=[
                t.PromptArgument(name=a.name, description=a.description, required=a.required)
                for a in p.arguments
            ],
        )
        for p in PROMPTS
    ]


def _validate(prompt: _Prompt, arguments: Mapping[str, str]) -> dict[str, str]:
    known = {a.name for a in prompt.arguments}
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise ToolError(
            "invalid_argument", f"Unknown argument(s) for {prompt.name}: {', '.join(unknown)}."
        )
    values = {k: str(v).strip() for k, v in arguments.items() if v is not None and str(v).strip()}
    missing = [a.name for a in prompt.arguments if a.required and a.name not in values]
    if missing:
        raise ToolError(
            "invalid_argument",
            f"Missing required argument(s) for {prompt.name}: {', '.join(missing)}.",
        )
    for key in ("start_month", "end_month"):
        if key in values and not _MONTH_RE.match(values[key]):
            raise ToolError("invalid_argument", f"{key} must be YYYY-MM.")
    if values.get("package") and values["package"] not in ("basic", "expanded"):
        raise ToolError("invalid_argument", "package must be basic or expanded.")
    return values


def _render(name: str, v: Mapping[str, str]) -> str:
    if name == "neon_find_data":
        extra = "".join(
            f"\n- {label}: {v[key]}"
            for key, label in (
                ("region", "Region"),
                ("timeframe", "Timeframe"),
                ("organism_or_variable", "Organism or variable"),
            )
            if key in v
        )
        return (
            f"Research question: {v['question']}{extra}\n\n"
            "Use the neon-mcp tools to find NEON data that can answer it:\n"
            "1. neon_search_products with keywords (and a theme or science_team when the question implies one); "
            "follow page.nextOffset if the first page is not conclusive.\n"
            "2. neon_search_sites for the region (query, state_code, domain_code, or latitude/longitude "
            "with radius_km).\n"
            "3. neon_get_availability for the best 1-3 products at those sites (window it with start_month/end_month); "
            "state which months are released and which are PROVISIONAL.\n"
            "4. Call neon_ping: if a token is configured, run neon_list_files(detail='summary') to size the data; "
            "otherwise explain that listing files needs a NEON API token (neon://guide/api-token).\n"
            "5. Finish with a table of candidate product x site x months, caveats from the results' notes, "
            "and neon_get_citation for each product."
        )
    if name == "neon_cite_dataset":
        release = f" for {v['release']}" if "release" in v else ""
        sites = (
            f" The data came from sites {v['site_codes']}; mention them."
            if "site_codes" in v
            else ""
        )
        return (
            f"Cite the NEON data product {v['product']}{release}. Call neon_get_citation"
            f"(product={v['product']!r}{', release=' + repr(v['release']) if 'release' in v else ''}). "
            "Present the citation text and the BibTeX entry. If the data used include PROVISIONAL months, "
            f"call it again with provisional=true and explain that provisional data have no DOI.{sites}"
        )
    end = v.get("end_month", v["start_month"])
    package = v.get("package", "basic")
    return (
        f"Plan a download of NEON product {v['product']} at sites {v['sites']} from {v['start_month']} to {end} "
        f"({package} package).\n"
        "1. neon_ping: confirm a NEON API token is configured and whether downloads are enabled.\n"
        "2. neon_get_availability for the product at those sites and months; report gaps and PROVISIONAL months.\n"
        "3. neon_list_files(detail='summary', include_urls=false) to size the pull (files, bytes, site-months).\n"
        "4. If downloads are enabled (stdio), neon_download_files with the same selectors (narrow with kind='data' "
        "or table= if the plan is large); otherwise hand back the signed URLs from neon_list_files and note they "
        "expire in about 7 days.\n"
        "5. neon_get_citation for the product."
    )


def get_prompt(name: str, arguments: Mapping[str, str] | None) -> t.GetPromptResult:
    prompt = next((p for p in PROMPTS if p.name == name), None)
    if prompt is None:
        raise ToolError(
            "not_found",
            f"Unknown prompt {name!r}.",
            details={"available": [p.name for p in PROMPTS]},
        )
    values = _validate(prompt, arguments or {})
    return t.GetPromptResult(
        description=prompt.description,
        messages=[
            t.PromptMessage(
                role="user", content=t.TextContent(type="text", text=_render(name, values))
            )
        ],
    )
