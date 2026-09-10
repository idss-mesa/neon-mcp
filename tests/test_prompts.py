from __future__ import annotations

import pytest

from neon_mcp.errors import ToolError
from neon_mcp.instructions import SERVER_INSTRUCTIONS
from neon_mcp.prompts import get_prompt, list_prompts


def test_listing() -> None:
    prompts = list_prompts()
    assert [p.name for p in prompts] == [
        "neon_cite_dataset",
        "neon_find_data",
        "neon_plan_download",
    ]
    required = {p.name: [a.name for a in p.arguments or [] if a.required] for p in prompts}
    assert required == {
        "neon_cite_dataset": ["product"],
        "neon_find_data": ["question"],
        "neon_plan_download": ["product", "sites", "start_month"],
    }


def text(name: str, args: dict[str, str]) -> str:
    content = get_prompt(name, args).messages[0].content
    return content.text  # type: ignore[union-attr]


def test_rendering() -> None:
    find = text("neon_find_data", {"question": "How do bird counts vary?", "region": "D01"})
    assert (
        "How do bird counts vary?" in find
        and "Region: D01" in find
        and "neon_get_availability" in find
    )
    assert "Timeframe" not in find
    cite = text(
        "neon_cite_dataset",
        {"product": "DP1.10003.001", "release": "RELEASE-2026", "site_codes": "HARV"},
    )
    assert "release='RELEASE-2026'" in cite and "HARV" in cite
    plan = text(
        "neon_plan_download",
        {"product": "DP1.00001.001", "sites": "HARV,ABBY", "start_month": "2023-01"},
    )
    assert "from 2023-01 to 2023-01" in plan and "basic" in plan and "neon_download_files" in plan


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("neon_find_data", {}),
        ("neon_cite_dataset", {"product": "x", "bogus": "1"}),
        ("neon_plan_download", {"product": "x", "sites": "HARV", "start_month": "2023-13"}),
        (
            "neon_plan_download",
            {"product": "x", "sites": "HARV", "start_month": "2023-01", "package": "big"},
        ),
        ("neon_nope", {}),
    ],
)
def test_validation(name: str, args: dict[str, str]) -> None:
    with pytest.raises(ToolError):
        get_prompt(name, args)


def test_instructions() -> None:
    assert len(SERVER_INSTRUCTIONS) <= 1200
    for phrase in (
        "neon_search_products",
        "token",
        "PROVISIONAL",
        "neon://guide/agent-workflow",
        "neon_ping",
    ):
        assert phrase in SERVER_INSTRUCTIONS
