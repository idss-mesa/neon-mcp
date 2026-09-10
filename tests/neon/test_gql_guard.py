from __future__ import annotations

import pytest

from neon_mcp.errors import ToolError
from neon_mcp.neon.gql_guard import check_query, prune_to_budget


def ok(query: str) -> None:
    check_query(query, max_chars=8000, max_depth=8)


def bad(query: str, match: str, **kw: int) -> None:
    with pytest.raises(ToolError, match=match) as exc:
        check_query(query, max_chars=kw.get("max_chars", 8000), max_depth=kw.get("max_depth", 8))
    assert exc.value.code == "invalid_argument"


@pytest.mark.parametrize(
    "query",
    [
        "{ sites { siteCode } }",
        "query Q($r: String) { sites(release: $r) { siteCode siteName } }",
        "{ s: sites { siteCode } p: products { productCode } }",
        '{ product(productCode: "DP1.00001.001") { productName } }  # comment { not a brace',
        '{ findLocations(query: {locationNames: ["HARV", "a{b"]}) { locationName } }',
        '{ __type(name: "Site") { name fields { name } } }',
        "fragment F on Site { siteCode } query { sites { ...F } }",
        "query A { sites { siteCode } } query B { products { productCode } }",
    ],
)
def test_accepted(query: str) -> None:
    ok(query)


def test_rejected() -> None:
    bad('mutation { deleteSite(code: "HARV") }', "read-only")
    bad("subscription { sites { siteCode } }", "read-only")
    bad("{ nope { x } }", "not allowed")
    bad('{ __schema { types { name } } __type(name: "Site") { name } }', "single")
    bad("{ a { b { c { d { e { f { g { h { i } } } } } } } } }", "depth")
    bad("{ sites { siteCode }", "Unbalanced")
    bad("{ sites { siteCode } } }", "Unbalanced")
    bad("x" * 20, "longer", max_chars=10)
    bad("   ", "empty")
    bad("{ ...Spread }", "Fragment spreads")
    bad("banana { sites { siteCode } }", "Unexpected token")
    bad("fragment F on Site { siteCode }", "no query operation")


def test_prune_to_budget_reports_paths() -> None:
    data = {
        "products": [
            {"productCode": f"DP1.{i:05d}.001", "productName": "x" * 40} for i in range(200)
        ],
        "small": [1, 2],
    }
    pruned, paths = prune_to_budget(data, 2000)
    assert len(str(pruned)) < len(str({"products": [0] * 200})) * 20
    assert paths and paths[0].startswith("data.products[")
    assert pruned["small"] == [1, 2]
    same, none = prune_to_budget({"a": 1}, 1000)
    assert same == {"a": 1} and none == []
