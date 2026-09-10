from __future__ import annotations

import pytest

from neon_mcp.server import NeonServer
from tests.fixture_router import PROTOTYPE_UUID, FixtureRouter, Reply, Route
from tests.helpers import call_err, call_ok

BLUE, MOSQ, SONAR = (
    PROTOTYPE_UUID,
    "08047ac5-16a1-4068-bf57-395886c147a3",
    "09a00d5d-ec6d-4cfd-9ab2-c8bfefae96b8",
)


def uuids(payload: dict) -> list[str]:  # type: ignore[type-arg]
    return [i["uuid"] for i in payload["items"]]


async def test_search_all_with_facets(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_search_prototype_datasets", {})
    assert uuids(payload) == [SONAR, MOSQ, BLUE] or len(payload["items"]) == 3
    assert payload["facets"]["fileTypes"]["CSV"] == 3
    assert "Aquatic Observational Systems (AOS)" in payload["facets"]["scienceTeams"]
    first = next(i for i in payload["items"] if i["uuid"] == BLUE)
    assert (
        first["siteCodes"] == ["BLUE"]
        and first["doi"]["url"] == "https://doi.org/10.48443/7ay8-e395"
    )
    assert router.paths() == ["GET /prototype/datasets"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"query": "reaeration"}, [BLUE]),
        ({"theme": "land cover"}, [SONAR]),
        ({"science_team": "tos"}, [MOSQ]),
        ({"site_code": "osbs"}, [MOSQ]),
        ({"start_year": 2012, "end_year": 2012}, [MOSQ]),
        ({"file_type": "shp"}, [SONAR]),
        ({"is_published": True}, []),
    ],
)
async def test_search_filters(server: NeonServer, args: dict, expected: list[str]) -> None:  # type: ignore[type-arg]
    assert sorted(uuids(await call_ok(server, "neon_search_prototype_datasets", args))) == sorted(
        expected
    )


async def test_get_dataset_with_files(server: NeonServer, router: FixtureRouter) -> None:
    payload = await call_ok(server, "neon_get_prototype_dataset", {"uuid": BLUE.upper()})
    assert router.paths() == [f"GET /prototype/datasets/{BLUE}", f"GET /prototype/data/{BLUE}"]
    assert (
        payload["projectTitle"].startswith("NEON prototype reaeration")
        and payload["version"] == "v1"
    )
    files = payload["files"]
    assert [f["fileName"] for f in files][1] == "NEON_reaeration_BLUE_2016.zip"
    assert files[1]["size"] == 4678798 and "REDACTED" in files[1]["url"]
    assert payload["locations"][0]["siteCode"] == "BLUE"
    assert payload["nextSteps"][0].startswith("neon_download_files(prototype_uuid=")
    assert any("expire" in n for n in payload["notes"])


async def test_get_dataset_options(server: NeonServer) -> None:
    no_urls = await call_ok(
        server,
        "neon_get_prototype_dataset",
        {"uuid": BLUE, "include_urls": False, "files_limit": 1},
    )
    assert "url" not in no_urls["files"][0] and no_urls["filesPage"]["nextOffset"] == 1
    everything = await call_ok(
        server, "neon_get_prototype_dataset", {"uuid": BLUE, "include": ["all"], "text_budget": 200}
    )
    assert len(everything["projectDescription"]) <= 200 and everything["publicationCitations"] == []
    bare = await call_ok(server, "neon_get_prototype_dataset", {"uuid": BLUE, "include": []})
    assert "files" not in bare and "locations" not in bare


async def test_get_dataset_errors(server: NeonServer, router: FixtureRouter) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    router.add(
        Route(
            "GET",
            f"/prototype/datasets/{missing}",
            Reply(
                json={
                    "error": {"status": 400, "detail": "Prototype dataset not found"},
                    "data": None,
                },
                status=400,
            ),
        )
    )
    await call_err(server, "neon_get_prototype_dataset", {"uuid": missing}, "not_found")
    await call_err(server, "neon_get_prototype_dataset", {"uuid": "not-a-uuid"}, "invalid_argument")
