from __future__ import annotations

from neon_mcp.server import NeonServer
from tests.fixture_router import FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok


async def test_introspect_type(token_server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(token_server, "neon_graphql", {"introspect_type": "Site"})
    assert payload["data"]["__type"]["name"] == "Site"
    assert router.calls[0].operation == "NeonMcpIntrospect"
    assert not router.calls[0].has_token  # never sends a token
    assert payload["schemaHint"] == "neon://reference/graphql-schema"
    assert payload["source"]["via"] == "graphql"


async def test_user_query_success_and_pruning(server: NeonServer, router: FixtureRouter) -> None:
    sites = [{"siteCode": f"S{i:03d}", "siteName": "x" * 50} for i in range(400)]
    router.add(
        Route(
            "POST",
            "graphql:",
            Reply(json={"data": {"sites": sites}}),
            body=lambda b: "sites" in b["query"],
        )
    )
    payload = await call_ok(
        server, "neon_graphql", {"query": "{ sites { siteCode siteName } }", "max_bytes": 5000}
    )
    assert payload["truncated"] is True and payload["truncatedPaths"][0].startswith("data.sites[")
    assert payload["bytesTotal"] > 5000 and len(payload["data"]["sites"]) < 400
    assert payload["nextSteps"]


async def test_errors_without_data(server: NeonServer) -> None:
    error = await call_err(
        server, "neon_graphql", {"query": "{ products { nope } }"}, "graphql_error"
    )
    assert error["details"]["errors"][0]["extensions"]["classification"] == "ValidationError"


async def test_bad_faith_introspection_and_not_found(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.add(
        Route(
            "POST",
            "graphql:",
            Reply(
                json={
                    "errors": [
                        {
                            "message": "too much",
                            "extensions": {"classification": "BadFaithIntrospection"},
                        }
                    ]
                }
            ),
            body=lambda b: "__schema" in b["query"],
        )
    )
    await call_err(
        server, "neon_graphql", {"query": "{ __schema { types { name } } }"}, "invalid_argument"
    )
    router.add(
        Route(
            "POST",
            "graphql:",
            Reply(json={"errors": [{"message": "Site not found"}], "data": {"site": None}}),
            body=lambda b: "ZZZZ" in b["query"],
        )
    )
    await call_err(
        server, "neon_graphql", {"query": '{ site(siteCode: "ZZZZ") { siteName } }'}, "not_found"
    )


async def test_partial_data_is_returned_with_errors(
    server: NeonServer, router: FixtureRouter
) -> None:
    router.add(
        Route(
            "POST",
            "graphql:",
            Reply(
                json={
                    "data": {"sites": [{"siteCode": "ABBY"}], "site": None},
                    "errors": [{"message": "Site not found"}],
                }
            ),
            body=lambda b: "partial" in b["query"],
        )
    )
    payload = await call_ok(
        server,
        "neon_graphql",
        {"query": '{ sites { siteCode } site(siteCode:"X") { siteCode } } # partial'},
    )
    assert payload["errors"] and payload["notes"]


async def test_guard_rails_reject_before_any_request(
    server: NeonServer, router: FixtureRouter
) -> None:
    await call_err(server, "neon_graphql", {"query": "mutation { x }"}, "invalid_argument")
    await call_err(
        server,
        "neon_graphql",
        {"query": "{ sites { siteCode } }", "introspect_type": "Site"},
        "invalid_argument",
    )
    await call_err(server, "neon_graphql", {}, "invalid_argument")
    assert router.calls == []
