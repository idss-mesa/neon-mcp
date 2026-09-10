from __future__ import annotations

from neon_mcp.server import NeonServer
from tests.fixture_router import TEST_TOKEN, FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok

TAG = "A00000123456"
CLASSES = ["bet_IDandpinning_in.individualID", "bet_sorting_in.subsampleID"]
CAPS = {"elicitation": {"form": {}}}


async def test_list_supported_classes(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_list_sample_classes", {})
    assert payload["sourceEndpoint"] == "supportedClasses" and payload["page"]["total"] == 8
    keys = [i["sampleClass"] for i in payload["items"]]
    assert keys == sorted(keys) and all(i["description"] for i in payload["items"])
    wdp = await call_ok(server, "neon_list_sample_classes", {"query": "wet deposition"})
    assert wdp["items"] and all("wdp" in i["sampleClass"] for i in wdp["items"])
    assert router.paths() == ["GET /samples/supportedClasses"]


async def test_classes_for_tag(server: NeonServer) -> None:
    payload = await call_ok(server, "neon_list_sample_classes", {"sample_tag": TAG})
    assert [i["sampleClass"] for i in payload["items"]] == CLASSES and payload[
        "sourceEndpoint"
    ] == "classes"
    assert payload["nextSteps"][0].startswith(f"neon_get_sample(sample_tag='{TAG}'")
    none = await call_ok(server, "neon_list_sample_classes", {"sample_tag": "NOPE"})
    assert none["items"] == [] and "no sample classes" in none["notes"][0]


async def test_get_sample_requires_token(server: NeonServer, router: FixtureRouter) -> None:
    await call_err(server, "neon_get_sample", {"barcode": TAG}, "auth_required")
    assert router.calls == []


async def test_get_by_barcode(token_server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(token_server, "neon_get_sample", {"barcode": TAG})
    call = router.calls_to("GET /samples/view")[0]
    assert call.params == {"barcode": TAG} and call.headers["x-api-token"] == TEST_TOKEN
    view = payload["items"][0]
    assert view["sampleUuid"] == "5e2b4c1a-0000-4000-8000-000000000001" and view["eventCount"] == 2
    assert view["sampleEvents"][0]["fields"]
    assert payload["identifier"] == {"mode": "barcode", "value": TAG}
    limited = await call_ok(token_server, "neon_get_sample", {"barcode": TAG, "events_limit": 1})
    assert (
        limited["items"][0]["eventsTruncated"] is True
        and len(limited["items"][0]["sampleEvents"]) == 1
    )
    bare = await call_ok(token_server, "neon_get_sample", {"barcode": TAG, "include_events": False})
    assert bare["items"][0]["sampleEvents"] == [] and bare["items"][0]["eventCount"] == 2


async def test_ambiguous_tag_without_elicitation(token_server: NeonServer) -> None:
    err = await call_err(token_server, "neon_get_sample", {"sample_tag": TAG}, "ambiguous_input")
    assert [c["code"] for c in err["details"]["candidates"]] == CLASSES


async def test_mrtr_round_trip(token_server: NeonServer, router: FixtureRouter) -> None:
    router.add(
        Route(
            "GET",
            "/samples/view",
            Reply(fixture="samples_view_barcode.json"),
            params={"sampleTag": TAG, "sampleClass": CLASSES[1]},
            token=True,
        )
    )
    first = await token_server.call(
        "neon_get_sample", {"sample_tag": TAG}, client_capabilities=CAPS
    )
    pending = first.input_required
    assert pending is not None and pending.key == "sample_class"
    assert pending.requested_schema["properties"]["choice"]["enum"] == CLASSES
    assert first.request_state and TEST_TOKEN not in first.request_state
    answer = {"sample_class": {"action": "accept", "content": {"choice": CLASSES[1]}}}
    second = await token_server.call(
        "neon_get_sample",
        {"sample_tag": TAG},
        client_capabilities=CAPS,
        input_responses=answer,
        request_state=first.request_state,
    )
    assert not second.is_error and second.payload["identifier"]["sampleClass"] == CLASSES[1]
    stale = {"sample_class": {"action": "accept", "content": {"choice": "bogus.class"}}}
    third = await token_server.call(
        "neon_get_sample",
        {"sample_tag": TAG},
        client_capabilities=CAPS,
        input_responses=stale,
        request_state=first.request_state,
    )
    assert third.payload["error"]["code"] == "invalid_argument"
    declined = {"sample_class": {"action": "decline"}}
    fourth = await token_server.call(
        "neon_get_sample",
        {"sample_tag": TAG},
        client_capabilities=CAPS,
        input_responses=declined,
        request_state=first.request_state,
    )
    assert fourth.payload["error"]["code"] == "invalid_argument"


async def test_explicit_class_and_degree(token_server: NeonServer, router: FixtureRouter) -> None:
    router.add(
        Route(
            "GET",
            "/samples/view",
            Reply(fixture="samples_view_barcode.json"),
            params={"sampleTag": TAG, "sampleClass": CLASSES[0]},
            token=True,
        ),
        Route(
            "GET",
            "/samples/download",
            Reply(fixture="samples_download_degree2.json"),
            params={"barcode": TAG, "degree": "2"},
            token=True,
        ),
    )
    tagged = await call_ok(
        token_server, "neon_get_sample", {"sample_tag": TAG, "sample_class": CLASSES[0]}
    )
    assert tagged["identifier"]["sampleClass"] == CLASSES[0]
    assert not [c for c in router.calls if c.path == "/samples/classes"]
    related = await call_ok(
        token_server, "neon_get_sample", {"barcode": TAG, "degree": 2, "fields": ["siteID"]}
    )
    assert related["degree"] == 2 and len(related["items"]) == 3
    assert related["items"][1]["sampleEvents"][0]["fields"] == {"siteID": "HARV"}
    assert any("child sample" in s for s in related["nextSteps"])


async def test_validation(token_server: NeonServer) -> None:
    await call_err(token_server, "neon_get_sample", {}, "invalid_argument")
    await call_err(
        token_server, "neon_get_sample", {"barcode": TAG, "sample_uuid": "x"}, "invalid_argument"
    )
    await call_err(
        token_server, "neon_get_sample", {"barcode": TAG, "sample_class": "x"}, "invalid_argument"
    )
    await call_err(token_server, "neon_get_sample", {"sample_tag": "NOPE"}, "not_found")
