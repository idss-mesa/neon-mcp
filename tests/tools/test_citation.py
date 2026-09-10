from __future__ import annotations

import copy

from neon_mcp.server import NeonServer
from tests.fixture_router import PROTOTYPE_UUID, FixtureRouter, Reply, Route, load_fixture
from tests.helpers import call_err, call_ok

DAY = "2026-09-10"


async def test_latest_release_citation(server: NeonServer) -> None:
    payload = await call_ok(
        server, "neon_get_citation", {"product": "DP1.10003.001", "accessed_on": DAY}
    )
    assert payload["release"] == "RELEASE-2026"
    assert (
        payload["doi"] == "10.48443/v6hs-mx57"
        and payload["doiUrl"] == "https://doi.org/10.48443/v6hs-mx57"
    )
    assert payload["accessedOn"] == "September 10, 2026"
    assert payload["citationText"] == (
        "NEON (National Ecological Observatory Network). Breeding landbird point counts (DP1.10003.001), "
        "RELEASE-2026. https://doi.org/10.48443/v6hs-mx57. Dataset accessed from https://data.neonscience.org "
        "on September 10, 2026."
    )
    bib = payload["bibtex"]
    assert bib.startswith("@misc{neon_dp1_10003_001_release_2026,")
    assert "doi = {10.48443/v6hs-mx57}" in bib and "year = {2026}" in bib
    assert "title = {Breeding landbird point counts (DP1.10003.001), RELEASE-2026}" in bib
    assert payload["dataPolicyUrl"].startswith("https://www.neonscience.org/")
    assert payload["notes"] == []


async def test_explicit_release_and_formats(server: NeonServer) -> None:
    text = await call_ok(
        server,
        "neon_get_citation",
        {
            "product": "DP1.00001.001",
            "release": "RELEASE-2025",
            "format": "text",
            "accessed_on": DAY,
        },
    )
    assert text["doi"] == "10.48443/te3v-2m97" and "bibtex" not in text and text["notes"] == []
    bib = await call_ok(
        server, "neon_get_citation", {"product": "DP1.00001.001", "format": "bibtex"}
    )
    assert "citationText" not in bib and bib["bibtex"]


async def test_doi_mismatch_is_noted(server: NeonServer, router: FixtureRouter) -> None:
    releases = copy.deepcopy(load_fixture("releases.json"))
    for rel in releases["data"]:
        for product in rel["dataProducts"]:
            product["productDoi"] = "https://doi.org/10.48443/other"
    router.add(Route("GET", "/releases", Reply(json=releases), params={}))
    payload = await call_ok(server, "neon_get_citation", {"product": "DP1.00001.001"})
    assert any("10.48443/other" in n for n in payload["notes"])


async def test_provisional_and_missing_dois(server: NeonServer) -> None:
    provisional = await call_ok(
        server,
        "neon_get_citation",
        {
            "product": "breeding landbird",
            "provisional": True,
            "accessed_on": DAY,
            "site_codes": ["HARV"],
        },
    )
    assert provisional["provisional"] is True and "doi" not in provisional
    assert (
        "provisional data. Dataset accessed from https://data.neonscience.org on September 10, 2026. "
        "Data archived at [your DOI]." in provisional["citationText"]
    )
    assert "doi =" not in provisional["bibtex"]
    assert (
        "Data for sites HARV." in provisional["notes"]
        and provisional["resolved"][0]["code"] == "DP1.10003.001"
    )
    wrong = await call_err(
        server,
        "neon_get_citation",
        {"product": "DP1.10003.001", "release": "RELEASE-2021"},
        "not_found",
    )
    assert wrong["details"]["availableReleases"] == ["RELEASE-2025", "RELEASE-2026"]
    none = await call_err(server, "neon_get_citation", {"product": "DP1.20002.001"}, "not_found")
    assert "provisional=true" in none["hint"]


async def test_prototype_citation(server: NeonServer) -> None:
    payload = await call_ok(
        server, "neon_get_citation", {"prototype_uuid": PROTOTYPE_UUID, "accessed_on": DAY}
    )
    assert payload["doi"] == "10.48443/7ay8-e395" and payload["projectTitle"].startswith(
        "NEON prototype reaeration"
    )
    assert "version v1" in payload["citationText"] and PROTOTYPE_UUID in payload["citationText"]
    assert "year = {2021}" in payload["bibtex"]


async def test_citation_validation(server: NeonServer) -> None:
    await call_err(server, "neon_get_citation", {}, "invalid_argument")
    await call_err(
        server,
        "neon_get_citation",
        {"product": "DP1.10003.001", "prototype_uuid": PROTOTYPE_UUID},
        "invalid_argument",
    )
    await call_err(
        server,
        "neon_get_citation",
        {"product": "DP1.10003.001", "provisional": True, "release": "RELEASE-2026"},
        "invalid_argument",
    )
