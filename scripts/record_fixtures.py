#!/usr/bin/env python3
"""Maintainer tool for the hermetic test fixtures in ``tests/fixtures/``.

Fixtures are real NEON responses recorded live, shrunk by hand (at most 3
sites / 6 months / 5 list items, every top-level key kept) and scrubbed of
signed-URL signatures. This script enforces the rules and derives the
GraphQL catalog fixtures deterministically from the REST ones.

    python scripts/record_fixtures.py check                 # CI: rules below
    python scripts/record_fixtures.py scrub                 # redact X-Goog-Signature / Credential values
    python scripts/record_fixtures.py derive-gql-catalog    # products.json/sites.json -> graphql_*_catalog.json
    python scripts/record_fixtures.py record URL NAME       # fetch an anonymous endpoint to fixtures/_raw/NAME

Rules checked: no ``X-Goog-Signature=`` other than ``REDACTED``; no
``apiToken=``; no ``X-API-Token`` value; every fixture <= 40 KB (except the
two payload-hazard samples, which no route may serve); total <= 3 MB.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MAX_FIXTURE_BYTES = 40 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
SIG_RE = re.compile(r"(X-Goog-Signature=)([^&\"\s]+)")
CRED_RE = re.compile(r"(X-Goog-Credential=)([^&\"\s]+)")
TOKEN_RE = re.compile(r"apiToken=|x-api-token:\s*\S", re.IGNORECASE)

PRODUCT_KEYS = (
    "productCode",
    "productName",
    "productDescription",
    "productStatus",
    "productScienceTeam",
    "productPublicationFormatType",
    "productHasExpanded",
    "themes",
    "keywords",
)
SITE_KEYS = (
    "siteCode",
    "siteName",
    "siteDescription",
    "siteType",
    "siteLatitude",
    "siteLongitude",
    "stateCode",
    "stateName",
    "domainCode",
    "domainName",
    "deimsId",
)


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _write(name: str, data: Any) -> None:
    (FIXTURES / name).write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def derive_gql_catalog() -> None:
    """Project the REST fixtures onto the exact GraphQL selections neon-mcp sends."""
    products = []
    for p in _load("products.json")["data"]:
        row = {k: p.get(k) for k in PRODUCT_KEYS}
        row["releases"] = [
            {
                "release": r.get("release"),
                "generationDate": r.get("generationDate"),
                "url": r.get("url"),
                "productDoi": r.get("productDoi"),
            }
            for r in p.get("releases") or []
        ]
        row["siteCodes"] = (
            [
                {"siteCode": s["siteCode"], "availableMonths": s.get("availableMonths")}
                for s in p["siteCodes"]
            ]
            if p.get("siteCodes") is not None
            else None
        )
        row["specs"] = (
            [
                {
                    "specNumber": s.get("specNumber"),
                    "specDescription": s.get("specDescription"),
                    "specType": s.get("specType"),
                    "specSize": str(s.get("specSize")),  # GraphQL types specSize as String
                }
                for s in p["specs"]
            ]
            if p.get("specs") is not None
            else None
        )
        products.append(row)
    _write("graphql_products_catalog.json", {"data": {"products": products}})

    sites = []
    for s in _load("sites.json")["data"]:
        row = {k: s.get(k) for k in SITE_KEYS}
        row["releases"] = [
            {"release": r.get("release"), "generationDate": r.get("generationDate")}
            for r in s.get("releases") or []
        ]
        row["dataProducts"] = [
            {
                "dataProductCode": d.get("dataProductCode"),
                "dataProductTitle": d.get("dataProductTitle"),
            }
            for d in s.get("dataProducts") or []
        ]
        sites.append(row)
    _write("graphql_sites_catalog.json", {"data": {"sites": sites}})
    print("wrote graphql_products_catalog.json and graphql_sites_catalog.json")


def scrub() -> int:
    changed = 0
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_file() or path.suffix not in (".json", ".headers", ".txt", ".md"):
            continue
        text = path.read_text(encoding="utf-8")
        new = CRED_RE.sub(r"\1REDACTED", SIG_RE.sub(r"\1REDACTED", text))
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print("scrubbed", path.name)
    return changed


# Deliberately oversized samples of the two payload-hazard endpoints; no route serves them.
HAZARD_SAMPLES = {"release_RELEASE-2025_products.json", "release_RELEASE-2025_sites.json"}


def check() -> int:
    problems: list[str] = []
    total = 0
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_FIXTURE_BYTES and path.name not in HAZARD_SAMPLES:
            problems.append(f"{path.name}: {size} bytes > {MAX_FIXTURE_BYTES}")
        if path.suffix in (".bin",):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in SIG_RE.finditer(text):
            if match.group(2) != "REDACTED":
                problems.append(f"{path.name}: unredacted X-Goog-Signature")
                break
        if TOKEN_RE.search(text):
            problems.append(f"{path.name}: contains an API token parameter/header")
    if total > MAX_TOTAL_BYTES:
        problems.append(f"fixtures total {total} bytes > {MAX_TOTAL_BYTES}")
    for problem in problems:
        print("FIXTURE:", problem)
    print(f"{len(problems)} problem(s); {total} bytes total")
    return 1 if problems else 0


def record(url: str, name: str) -> None:
    import urllib.request

    raw_dir = FIXTURES / "_raw"
    raw_dir.mkdir(exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "neon-mcp-fixture-recorder"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - maintainer tool, https only
        body = response.read().decode("utf-8")
    body = CRED_RE.sub(r"\1REDACTED", SIG_RE.sub(r"\1REDACTED", body))
    (raw_dir / name).write_text(body, encoding="utf-8")
    print(f"recorded {len(body)} bytes to tests/fixtures/_raw/{name}; shrink by hand before use")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command = argv[0]
    if command == "check":
        return check()
    if command == "scrub":
        scrub()
        return 0
    if command == "derive-gql-catalog":
        derive_gql_catalog()
        return 0
    if command == "record" and len(argv) == 3 and argv[1].startswith("https://"):
        record(argv[1], argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
