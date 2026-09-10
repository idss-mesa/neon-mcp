from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Iterator
from typing import Any, ClassVar

import pytest
from pydantic import Field

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import NeonInput, NeonOutput, Page, ToolResultBase
from neon_mcp.registry import (
    decode_request_state,
    encode_request_state,
    fit_to_budget,
    get_registered_tools,
    invoke,
    json_size,
    register_tool,
    unregister_tool,
)
from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter

DESC = "Test tool. Next: call another tool."


class EchoIn(NeonInput):
    product_code: str = Field(description="A code.")
    start_month: str | None = None


class EchoOut(ToolResultBase):
    product_code: str
    start_month: str | None = None


class Item(NeonOutput):
    name: str
    url: str | None = None


class ListOut(ToolResultBase):
    budget_list: ClassVar[str | None] = "items"
    budget_elide_fields: ClassVar[tuple[str, ...]] = ("url",)
    budget_elide_flag: ClassVar[str | None] = "urls_elided"
    items: list[Item] = Field(default_factory=list)
    page: Page | None = None
    urls_elided: bool = False


@pytest.fixture
def temp_tools() -> Iterator[Callable[..., Callable[[Any], Any]]]:
    names: list[str] = []

    def reg(name: str, **kw: Any) -> Callable[[Any], Any]:
        kw.setdefault("title", "T")
        kw.setdefault("description", DESC)
        kw.setdefault("input_model", EchoIn)
        kw.setdefault("output_model", EchoOut)
        kw.setdefault("surface", "core")
        kw.setdefault("endpoints", [])

        def deco(fn: Any) -> Any:
            register_tool(name, **kw)(fn)
            names.append(name)
            return fn

        return deco

    yield reg
    for name in names:
        unregister_tool(name)


async def echo(args: EchoIn, ctx: ToolContext) -> EchoOut:
    return EchoOut(product_code=args.product_code, start_month=args.start_month)


@pytest.mark.parametrize(
    ("kw", "exc"),
    [
        ({"name": "Bad-Name"}, ValueError),
        ({"description": "x" * 601 + " Next: y."}, ValueError),
        ({"description": "No follow-up sentence."}, ValueError),
        ({"input_model": dict}, TypeError),
        ({"output_model": NeonOutput}, TypeError),
        ({"surface": "nope"}, ValueError),
    ],
)
def test_registration_is_validated(kw: dict[str, Any], exc: type[Exception]) -> None:
    base: dict[str, Any] = {
        "title": "T",
        "description": DESC,
        "input_model": EchoIn,
        "output_model": EchoOut,
        "surface": "core",
        "endpoints": [],
    }
    name = kw.pop("name", "neon_test_bad")
    base.update(kw)
    with pytest.raises(exc):
        register_tool(name, **base)


def test_duplicate_and_filtering(temp_tools: Callable[..., Any]) -> None:
    temp_tools("neon_test_b", transports=("stdio",), needs_downloads=True)(echo)
    temp_tools("neon_test_a")(echo)
    with pytest.raises(ValueError, match="already registered"):
        register_tool(
            "neon_test_a",
            title="T",
            description=DESC,
            input_model=EchoIn,
            output_model=EchoOut,
            surface="core",
            endpoints=[],
        )(echo)
    names = [s.name for s in get_registered_tools()]
    assert names == sorted(names)
    assert "neon_test_b" not in [s.name for s in get_registered_tools(transport="http")]
    assert "neon_test_b" not in [s.name for s in get_registered_tools(downloads_enabled=False)]
    assert "neon_test_b" in [s.name for s in get_registered_tools(transport="stdio")]


async def test_invoke_accepts_snake_and_camel(
    server: NeonServer, temp_tools: Callable[..., Any]
) -> None:
    temp_tools("neon_test_echo")(echo)
    from neon_mcp.registry import get_tool

    spec = get_tool("neon_test_echo")
    ctx = server.tool_context(spec.name)
    a = await invoke(spec, {"product_code": "DP1.00001.001", "start_month": "2020-01"}, ctx)
    b = await invoke(spec, {"productCode": "DP1.00001.001", "startMonth": "2020-01"}, ctx)
    assert a["productCode"] == b["productCode"] == "DP1.00001.001"
    assert a["startMonth"] == "2020-01"
    assert a["source"]["via"] == "local"


async def test_unknown_argument_names_valid_ones(
    server: NeonServer, temp_tools: Callable[..., Any]
) -> None:
    temp_tools("neon_test_echo")(echo)
    outcome = await server.call("neon_test_echo", {"product_code": "x", "bogus": 1})
    err = outcome.payload["error"]
    assert outcome.is_error and err["code"] == "invalid_argument"
    assert "bogus" in err["message"] and "product_code" in err["message"]


async def test_token_tools_fail_before_the_handler(
    server: NeonServer, router: FixtureRouter, temp_tools: Callable[..., Any]
) -> None:
    ran: list[bool] = []

    async def handler(args: EchoIn, ctx: ToolContext) -> EchoOut:
        ran.append(True)
        return EchoOut(product_code="x")

    temp_tools("neon_test_token", requires_token=True)(handler)
    outcome = await server.call("neon_test_token", {"product_code": "x"})
    assert outcome.payload["error"]["code"] == "auth_required"
    assert ran == [] and router.calls == []


async def test_upstream_errors_are_mapped(
    server: NeonServer, temp_tools: Callable[..., Any]
) -> None:
    async def handler(args: EchoIn, ctx: ToolContext) -> EchoOut:
        raise NeonApiError(400, "Product code not found", "/products/DP9.99999.999")

    temp_tools("neon_test_notfound")(handler)
    outcome = await server.call("neon_test_notfound", {"product_code": "x"})
    assert outcome.payload["error"]["code"] == "not_found"


async def test_wrong_result_type_is_internal_error(
    server: NeonServer, temp_tools: Callable[..., Any]
) -> None:
    async def handler(args: EchoIn, ctx: ToolContext) -> Any:
        return {"not": "a model"}

    temp_tools("neon_test_wrong")(handler)
    outcome = await server.call("neon_test_wrong", {"product_code": "x"})
    assert outcome.payload["error"]["code"] == "internal_error"


def _list_payload(n: int, url_len: int = 200) -> dict[str, Any]:
    return {
        "items": [{"name": f"n{i}", "url": "https://x/" + "a" * url_len} for i in range(n)],
        "page": {"total": n, "returned": n, "offset": 10, "limit": n, "truncated": False},
        "nextSteps": [],
        "urlsElided": False,
    }


def test_budget_elides_urls_before_dropping() -> None:
    payload = fit_to_budget(_list_payload(50), ListOut, 6000)
    assert json_size(payload) <= 6000
    assert payload["urlsElided"] is True
    assert len(payload["items"]) == 50
    assert payload["items"][0]["url"] is not None or payload["items"][-1]["url"] is None
    assert payload["page"]["truncated"] is False


def test_budget_drops_items_and_rewrites_page() -> None:
    payload = fit_to_budget(_list_payload(50), ListOut, 600)
    assert json_size(payload) <= 600
    kept = len(payload["items"])
    assert 0 < kept < 50
    assert payload["page"] == {
        "total": 50,
        "returned": kept,
        "offset": 10,
        "limit": 50,
        "truncated": True,
        "nextOffset": 10 + kept,
        "truncatedReason": "budget",
    }
    assert "offset=" in payload["nextSteps"][-1]


def test_budget_passthrough_without_budget_list() -> None:
    payload = {"productCode": "x" * 10_000}
    assert fit_to_budget(dict(payload), EchoOut, 100) == payload


async def test_hard_cap_raises(server: NeonServer, temp_tools: Callable[..., Any]) -> None:
    async def handler(args: EchoIn, ctx: ToolContext) -> EchoOut:
        return EchoOut(product_code="x" * 5000)

    temp_tools("neon_test_big")(handler)
    server.config.limits.max_result_bytes = 1000
    server.config.limits.hard_max_result_bytes = 1000
    outcome = await server.call("neon_test_big", {"product_code": "x"})
    assert outcome.payload["error"]["code"] == "result_too_large"


def test_request_state_round_trip_and_rejections() -> None:
    state = {
        "v": 1,
        "tool": "neon_x",
        "issuedAt": time.time(),
        "field": "f",
        "candidates": ["a", "b"],
    }
    encoded = encode_request_state(state)
    assert decode_request_state(encoded, expected_tool="neon_x") == state
    with pytest.raises(ToolError, match="different tool"):
        decode_request_state(encoded, expected_tool="neon_y")
    with pytest.raises(ToolError, match="expired"):
        decode_request_state(encoded, expected_tool="neon_x", now=time.time() + 7200)
    with pytest.raises(ToolError):
        decode_request_state("!!!not-base64!!!", expected_tool="neon_x")
    with pytest.raises(ToolError):
        decode_request_state("x" * 40_000, expected_tool="neon_x")
    wrong_version = base64.urlsafe_b64encode(json.dumps({**state, "v": 2}).encode()).decode()
    with pytest.raises(ToolError, match="version"):
        decode_request_state(wrong_version, expected_tool="neon_x")
    future = encode_request_state({**state, "issuedAt": time.time() + 3600})
    with pytest.raises(ToolError, match="issue time"):
        decode_request_state(future, expected_tool="neon_x")


def test_request_state_refuses_credentials_and_oversize() -> None:
    with pytest.raises(ToolError, match="credential"):
        encode_request_state({"args": {"api_token": "x"}})
    with pytest.raises(ToolError, match="too large"):
        encode_request_state({"blob": "x" * 20_000})
