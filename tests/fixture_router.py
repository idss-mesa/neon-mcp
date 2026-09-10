"""Hermetic stand-in for the NEON Data API (an ``httpx.MockTransport`` handler).

Every request a test makes is matched against a route table built from
``tests/fixtures``. The router replays NEON's rate-limit headers, answers
token endpoints with NEON's real 403 body when ``X-API-Token`` is missing,
records every request in :attr:`FixtureRouter.calls` (so tests can assert
call counts, cache hits and that a token never reached a storage host), and
fails the test on any request it has no route for.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
API_HOST = "data.neonscience.org"
API_PREFIX = "/api/v0"
ANY = "*"
TEST_TOKEN = "unit-test-token-DO-NOT-LOG"
PROTOTYPE_UUID = "07dccab1-4990-4d2f-9c5b-bf97e10517e3"
RELEASE_2025_UUID = "e97870c2-bca7-4696-b6ff-45cb42fcbf53"
RELEASE_2026_UUID = "c28725ff-5aa2-41fa-845e-a7f1c8239d09"


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def load_fixture(name: str) -> Any:
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def load_headers(name: str) -> dict[str, str]:
    """Parse a recorded ``curl -D`` header file (the status line is skipped)."""
    out: dict[str, str] = {}
    for line in fixture_path(name).read_text(encoding="utf-8").splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


@dataclass
class Reply:
    fixture: str | None = None
    status: int = 200
    json: Any = None
    content: bytes | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: str = "application/json"


@dataclass
class Call:
    method: str
    url: str
    host: str
    path: str
    params: dict[str, Any]
    headers: dict[str, str]
    body: Any
    operation: str | None

    @property
    def has_token(self) -> bool:
        return "x-api-token" in self.headers

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


Responder = Reply | Callable[[Call], Reply]


@dataclass
class Route:
    method: str
    path: str
    reply: Responder
    params: Mapping[str, Any] | None = None
    body: Callable[[Any], bool] | None = None
    token: bool = False


def _params_match(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    if set(expected) != set(actual):
        return False
    for key, value in expected.items():
        if value == ANY:
            continue
        want = [str(v) for v in value] if isinstance(value, (list, tuple)) else str(value)
        got = actual[key]
        if want != got:
            return False
    return True


class FixtureRouter:
    def __init__(self, extra_routes: list[Route] | None = None, *, defaults: bool = True) -> None:
        self.routes: list[Route] = list(extra_routes or [])
        if defaults:
            self.routes.extend(default_routes(self))
        self.calls: list[Call] = []
        self.unexpected: list[str] = []
        self.drift_catalog = False
        self.fail_graphql = False
        self._queued: list[Reply] = []
        self.ok_headers = {
            k: v
            for k, v in load_headers("example_200.headers").items()
            if k.startswith("x-ratelimit")
        }

    # ------------------------------------------------------------- configuration

    def add(self, *routes: Route) -> None:
        """Add routes with priority over the defaults."""
        self.routes[:0] = list(routes)

    def inject(self, reply: Reply, times: int = 1) -> None:
        """Serve ``reply`` to the next ``times`` requests regardless of route."""
        self._queued.extend([reply] * times)

    def inject_429(self, times: int = 1) -> None:
        self.inject(
            Reply(
                fixture="rate_limited_429.json",
                status=429,
                headers=load_headers("rate_limited_429.headers"),
            ),
            times,
        )

    def inject_5xx(self, times: int = 1) -> None:
        self.inject(
            Reply(
                content=fixture_path("error_500.txt").read_bytes(),
                status=502,
                content_type="text/html",
            ),
            times,
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # ------------------------------------------------------------- inspection

    def calls_to(self, key: str) -> list[Call]:
        """Calls whose ``"METHOD path"`` equals ``key`` (e.g. ``"GET /products"``)."""
        return [c for c in self.calls if c.key == key]

    def paths(self) -> list[str]:
        return [c.key for c in self.calls]

    def reset(self) -> None:
        self.calls.clear()

    # ------------------------------------------------------------- handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        call = self._record(request)
        if self._queued:
            return self._respond(self._queued.pop(0), call)
        route = self._match(call)
        if route is None:
            message = f"unexpected upstream call: {call.method} {call.url}"
            self.unexpected.append(message)
            raise AssertionError(message)
        if route.token and not call.has_token:
            fixture = (
                "dataquery_403.json" if call.path.startswith("/data/query") else "data_403.json"
            )
            return self._respond(
                Reply(fixture=fixture, status=403, headers=load_headers("example_403.headers")),
                call,
            )
        reply = route.reply(call) if callable(route.reply) else route.reply
        return self._respond(reply, call)

    def _record(self, request: httpx.Request) -> Call:
        parts = urlsplit(str(request.url))
        host = (parts.hostname or "").lower()
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content
        operation = body.get("operationName") if isinstance(body, dict) else None
        if host == API_HOST and parts.path.startswith(API_PREFIX):
            path = parts.path[len(API_PREFIX) :]
        elif host == API_HOST and parts.path == "/graphql":
            path = f"graphql:{operation or ''}"
        else:
            path = f"https://{host}{parts.path}"
        params: dict[str, Any] = {}
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key in params:
                existing = params[key]
                params[key] = (
                    [*existing, value] if isinstance(existing, list) else [existing, value]
                )
            else:
                params[key] = value
        call = Call(
            method=request.method,
            url=str(request.url),
            host=host,
            path=path,
            params=params,
            headers={k.lower(): v for k, v in request.headers.items()},
            body=body,
            operation=operation,
        )
        self.calls.append(call)
        return call

    def _match(self, call: Call) -> Route | None:
        for route in self.routes:
            if route.method != call.method or route.path != call.path:
                continue
            if route.params is not None and not _params_match(route.params, call.params):
                continue
            if route.body is not None and not route.body(call.body):
                continue
            return route
        return None

    def _respond(self, reply: Reply, call: Call) -> httpx.Response:
        if reply.content is not None:
            content = reply.content
        elif reply.json is not None:
            content = json.dumps(reply.json).encode("utf-8")
        elif reply.fixture:
            content = fixture_path(reply.fixture).read_bytes()
        else:
            content = b""
        headers = {"content-type": reply.content_type}
        if call.host == API_HOST:
            headers.update(self.ok_headers)
        headers.update({k.lower(): v for k, v in reply.headers.items()})
        return httpx.Response(reply.status, content=content, headers=headers)


def fixture(name: str, status: int = 200) -> Reply:
    return Reply(fixture=name, status=status)


def default_routes(router: FixtureRouter) -> list[Route]:
    """The default route table (DESIGN.md section 12)."""

    def gql(name: str) -> Callable[[Call], Reply]:
        def respond(_call: Call) -> Reply:
            if router.fail_graphql:
                return Reply(content=b"<html>502</html>", status=502, content_type="text/html")
            return fixture(name)

        return respond

    def products_catalog(call: Call) -> Reply:
        if router.drift_catalog:
            return fixture("graphql_products_compact.json")
        return gql("graphql_products_catalog.json")(call)

    def is_query(product: str, sites: list[str]) -> Callable[[Any], bool]:
        return lambda b: (
            isinstance(b, dict) and b.get("productCode") == product and b.get("siteCodes") == sites
        )

    F = fixture
    return [
        # products
        Route("GET", "/products", F("products.json"), params={}),
        Route(
            "GET",
            "/products/DP1.00001.001",
            F("product_DP1.00001.001_RELEASE-2025.json"),
            params={"release": "RELEASE-2025"},
        ),
        Route(
            "GET",
            "/products/DP1.00001.001",
            F("release_400_not_found.json", 400),
            params={"release": "RELEASE-1999"},
        ),
        Route(
            "GET",
            "/products",
            F("release_400_not_found.json", 400),
            params={"release": "RELEASE-1999"},
        ),
        Route("GET", "/products/DP1.00001.001", F("product_DP1.00001.001.json"), params={}),
        Route("GET", "/products/DP1.10003.001", F("product_DP1.10003.001.json"), params={}),
        Route("GET", "/products/DP9.99999.999", F("product_404.json", 400)),
        # sites
        Route("GET", "/sites", F("sites.json"), params={}),
        Route("GET", "/sites/ABBY", F("site_ABBY.json"), params={}),
        Route("GET", "/sites/HARV", F("site_HARV.json"), params={}),
        Route("GET", "/sites/ZZZZ", F("site_404.json", 400)),
        # locations
        Route("GET", "/locations/sites", F("locations_sites.json"), params={}),
        Route(
            "GET",
            "/locations/HARV",
            F("location_HARV_hierarchy_TOWER.json"),
            params={"hierarchy": "true", "locationType": "TOWER"},
        ),
        Route(
            "GET",
            "/locations/HARV",
            F("location_HARV_hierarchy.json"),
            params={"hierarchy": "true"},
        ),
        Route("GET", "/locations/HARV", F("location_HARV.json"), params={}),
        Route("GET", "/locations/D01", F("location_D01.json"), params={}),
        Route(
            "GET",
            "/locations/REALM",
            F("location_REALM_hierarchy_DOMAIN.json"),
            params={"hierarchy": "true", "locationType": "DOMAIN"},
        ),
        Route("GET", "/locations/TOWER100450", F("location_TOWER100450.json"), params={}),
        Route(
            "GET", "/locations/HARV", F("location_HARV_history.json"), params={"history": "true"}
        ),
        Route("GET", "/locations/NOPE_NOT_A_LOCATION", F("location_404.json", 400)),
        # data (token)
        Route(
            "GET",
            "/data/DP1.00001.001/ABBY/2023-01",
            F("data_DP1.00001.001_ABBY_2023-01.json"),
            params={"package": "basic"},
            token=True,
        ),
        Route(
            "POST",
            "/data/query",
            F("dataquery_DP1.00001.001_ABBY.json"),
            body=is_query("DP1.00001.001", ["ABBY"]),
            token=True,
        ),
        # releases
        Route("GET", "/releases", F("releases.json"), params={}),
        Route("GET", "/releases/RELEASE-2025", F("release_RELEASE-2025.json"), params={}),
        Route("GET", f"/releases/{RELEASE_2025_UUID}", F("release_RELEASE-2025.json"), params={}),
        Route(
            "GET",
            "/releases/RELEASE-2025/products/DP1.00001.001",
            F("release_RELEASE-2025_product_DP1.00001.001.json"),
        ),
        Route("GET", "/releases/RELEASE-1999", F("release_400_not_found.json", 400)),
        # taxonomy
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_TICK_ping.json"),
            params={"taxonTypeCode": "TICK", "limit": "1"},
        ),
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_BIRD_p1.json"),
            params={"taxonTypeCode": "BIRD", "verbose": "false", "offset": "0", "limit": "5"},
        ),
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_BIRD_verbose.json"),
            params={"taxonTypeCode": "BIRD", "verbose": "true", "offset": "0", "limit": "2"},
        ),
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_genus_Quercus.json"),
            params={"genus": "Quercus", "verbose": "false", "offset": "0", "limit": "5"},
        ),
        # samples
        Route("GET", "/samples/supportedClasses", F("samples_supportedClasses.json")),
        Route(
            "GET",
            "/samples/classes",
            F("samples_classes_ok.json"),
            params={"sampleTag": "A00000123456"},
        ),
        Route(
            "GET",
            "/samples/classes",
            F("samples_classes_404.json", 404),
            params={"sampleTag": "NOPE"},
        ),
        Route(
            "GET",
            "/samples/view",
            F("samples_view_barcode.json"),
            params={"barcode": "A00000123456"},
            token=True,
        ),
        # prototype datasets
        Route("GET", "/prototype/datasets", F("prototype_datasets.json")),
        Route("GET", f"/prototype/datasets/{PROTOTYPE_UUID}", F("prototype_dataset_07dccab1.json")),
        Route("GET", f"/prototype/data/{PROTOTYPE_UUID}", F("prototype_data_07dccab1.json")),
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_genus_Quercus.json"),
            params={"genus": "Quercus", "verbose": "false", "offset": "0", "limit": "100"},
        ),
        Route(
            "GET",
            "/taxonomy",
            F("taxonomy_empty.json"),
            params={"scientificname": ANY, "verbose": "false", "offset": "0", "limit": ANY},
        ),
        Route(
            "POST",
            "/data/query",
            F("dataquery_DP1.00001.001_ABBY_HARV.json"),
            body=is_query("DP1.00001.001", ["ABBY", "HARV"]),
            token=True,
        ),
        # GraphQL, keyed by operationName
        Route("POST", "graphql:NeonMcpProductsCatalog", products_catalog),
        Route("POST", "graphql:NeonMcpSitesCatalog", gql("graphql_sites_catalog.json")),
        Route("POST", "graphql:NeonMcpSitesForRelease", gql("graphql_sites_compact.json")),
        Route(
            "POST",
            "graphql:NeonMcpProductAvailability",
            gql("graphql_filterProducts_availability.json"),
        ),
        Route(
            "POST", "graphql:NeonMcpSiteAvailability", gql("graphql_filterSites_availability.json")
        ),
        Route("POST", "graphql:NeonMcpLocations", gql("graphql_findLocations.json")),
        Route("POST", "graphql:NeonMcpIntrospect", gql("graphql_introspect_Site.json")),
        Route("POST", "graphql:", F("graphql_error.json")),
    ]
