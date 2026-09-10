# neon-mcp — verified research brief (2026-09-10)

Everything below was verified live on 2026-09-10 (curl against the NEON API, introspection of the installed
`mcp` 2.2.0 SDK, reading the sibling repos). Treat it as ground truth; re-verify only if something contradicts it.

## 0. Goal

Build a NEW MCP server for the NEON Data API, to be published at https://github.com/idss-mesa/neon-mcp.
Project dir: `/Users/tswetnam/github/neon-mcp` (currently empty, not a git repo).
It supersedes the old TypeScript server at `/private/tmp/claude-501/-Users-tswetnam-github-neon-mcp/f6d5b2e4-217b-4166-ad37-b974094df3f5/scratchpad/neon-data-api/mcp/` (SDK 1.x, spec 2024-11-05, 15 tools).
The new server MUST target the **MCP 2026-07-28 specification** (stateless core) via the **Python `mcp` SDK 2.x** (2.2.0 is current).

### Decisions already made (do not re-litigate)
- **Language: Python 3.11+**, `mcp>=2.0,<3`, hatchling, ruff, mypy, pytest (asyncio_mode=auto), pydantic v2, structlog, httpx.
  Rationale: the org's flagship server `idss-mesa/mesa-mcp` (local checkout: `/Users/tswetnam/github/idss-mesa/mesa-mcp`) is exactly this stack and already has a
  2026-07-28 conformance suite + stateless Streamable HTTP transport we can port. Its patterns are the house style.
- **Package/CLI name:** `neon-mcp` (PyPI-style dist name), Python package `neon_mcp`, console script `neon-mcp`.
- **Tool prefix:** `neon_` (continuity with the old server; the org uses `ds_`/`mesa_` for its other servers).
- **License:** MIT, "Copyright (c) 2026 The Regents of the University of New Mexico" (same as mesa-mcp).
- **Transports:** `stdio` (primary, for Claude Code/Desktop/Codex/OpenCode) and stateless **Streamable HTTP** at `/mcp` (`StreamableHTTPSessionManager(stateless=True)`), plus `GET /healthz`. NO legacy SSE transport (deprecated by the spec; nothing forces us to carry it). No OIDC (NEON data is public; the only credential is the user's NEON API token).
- **No deprecated MCP features:** no roots, no sampling, no `logging/setLevel`, no `ping` reliance, no SSE. Logs go to stderr (stdio) / JSON (http).
- **Env prefix:** `NEON_MCP_` with `__` section delimiter (mirrors `MESA_MCP_...`). Precedence: CLI flag > env > YAML > defaults.

## 1. NEON Data API — verified facts

Base URL: `https://data.neonscience.org/api/v0` (Swagger 2.0 doc version **0.11.0**; upstream repo https://github.com/NEONScience/neon-data-api, latest commit 2026-06-29).
GraphQL endpoint: **`https://data.neonscience.org/graphql`** (POST JSON `{"query": ...}`); NOTE `/api/v0/graphql` returns 404.
Docs site: https://data.neonscience.org/data-api/ (SPA; the markdown sources are in the repo under `docs/content/`; local copies of upstream endpoint docs are in the scratchpad as `up_*.md`, and `upstream-swagger.json`).

### 1.1 Authentication (NEW since v0.11.0, 2026-06)
- API token sent as header `X-API-Token: <token>` or query param `apiToken=<token>`. Tokens come from https://data.neonscience.org/myaccount .
- Swagger 0.11.0 declares a global `X-API-Token` apiKey security scheme, with explicit `security: []` (public) on: products, sites, locations, taxonomy, releases (list/detail/products/sites), samples/classes, samples/supportedClasses, prototype/*.
- **Endpoints that REQUIRE a token** (docs say "Requires Authentication"; verified live: they return `HTTP 403 {"error":{"status":403,"detail":"Access Denied"},"data":null}` without a token):
  - `GET /data/{productCode}/{siteCode}/{year-month}` (+ `/{filename}`), `GET /data/package/{productCode}/{siteCode}/{year-month}`
  - `GET /data/query`, `POST /data/query`
  - `GET /releases/{releaseTag}/data/...` (all three data variants)
  - `GET /samples/view`, `GET /samples/download`
- Everything else works anonymously. Consequence for the MCP server: it must run usefully with NO token (discovery, availability from `/products`, sites, locations, taxonomy, releases, prototype datasets) and unlock file listing/downloads/sample tracking when `NEON_MCP_NEON__API_TOKEN` (or equivalent) is configured. Tools that hit token-only endpoints must fail with a structured, actionable error (`auth_required`, link to myaccount page) — never a raw 403 stack.
- Tokens are secrets: never log them, never echo them in tool output or error details, never put them in MRTR `requestState` (it round-trips through the client).

### 1.2 Rate limiting (verified headers on every response)
- Headers: `X-RateLimit-Limit` (burst), `X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds), and on 429 a `RetryAfter` header + body `{"message":"API rate limit exceeded"}`.
- Anonymous (per IP): burst **200**, refill **2 req/s**. With token (`rate:public` scope): burst **2000**, **8 req/s** (docs v0.11.0; older docs said 1000/4).
- Client design implication: single shared async HTTP client, respect `X-RateLimit-Remaining` (sleep when low), retry 429 honoring `RetryAfter`, exponential backoff on 5xx, no retry on 4xx other than 429.

### 1.3 Endpoint catalogue (Swagger 0.11.0 — no path/schema differences vs the 0.10.0 fork; only security annotations + docs changed)
Products
- `GET /products?release=` → `{"data":[product...]}` — **202 products, 30.3 MB**, ~1.1 s. Item keys: productCodeLong, productCode, productCodePresentation, productName, productDescription, productStatus (ACTIVE 173 / FUTURE 29), productCategory (Level 1..4 Data Product), productHasExpanded, productScienceTeamAbbr (TIS 56, TOS 42, AOP 41, AOS 40, AIS 23), productScienceTeam, productPublicationFormatType, productAbstract, productDesignDescription, productStudyDescription, productBasicDescription, productExpandedDescription, productSensor, productRemarks, themes[], changeLogs[] (can be 100s), specs[] ({specId, specNumber, specType, specSize, specDescription, specUrl}), keywords[], biorepositoryCollections[]|null, releases[] ({release, generationDate, url, productDoi:{generationDate,url}}), siteCodes[] ({siteCode, availableMonths[] 'YYYY-MM', availableDataUrls[], availableReleases[] ({release:'RELEASE-2025'|'PROVISIONAL', availableMonths[]})}).
- `GET /products/{productCode}?release=` → single product; **~1 MB** for DP1.00001.001 (80 sites × 125 months). Themes seen: Biogeochemistry, Atmosphere, "Land Use, Land Cover, and Land Processes", Ecohydrology, "Organisms, Populations, and Communities".
Sites
- `GET /sites?release=` → **26.8 MB**; `GET /sites/{siteCode}` → ~317 KB. Keys: siteCode, siteName, siteDescription, siteType (GRADIENT|CORE), siteLatitude, siteLongitude, stateCode, stateName, domainCode (D01..D20), domainName, deimsId, releases[] ({release, generationDate, url}), dataProducts[] ({dataProductCode, dataProductTitle, availableMonths[], availableDataUrls[], availableReleases[]}).
Locations
- `GET /locations/sites` → 88 SITE-type locations, 2.7 MB. `GET /locations/{locationName}?history=&hierarchy=&locationType=` → location (HARV ≈ 61 KB; with `hierarchy=true` includes locationParentHierarchy chain SITE→DOMAIN(D01)→REALM and locationChildHierarchy[595]). Keys: locationName, locationDescription, locationType (SITE, DOMAIN, TOWER, CONFIG, ...), domainCode, siteCode, locationDecimalLatitude/Longitude, locationElevation, locationUtmEasting/Northing/Hemisphere/Zone, alpha/beta/gammaOrientation, x/y/zOffset, offsetLocation, locationPolygon, activePeriods[], locationProperties[] ({locationPropertyName, locationPropertyValue}), locationHistory[], locationParent, locationParentUrl, locationParentHierarchy, locationChildren[], locationChildrenUrls[], locationChildHierarchy[].
Data (TOKEN REQUIRED)
- `GET /data/{productCode}/{siteCode}/{year-month}?package=basic|expanded&release=` → `data:{productCode, siteCode, month, release, packages[]({type,url}), files[]({name,size,md5,crc32 (deprecated),crc32c,url}), externalData[]({name,type,url})}`. File `url`s are Google Cloud Storage signed URLs that **expire 7 days** after generation (was 1 hour in older docs).
- `GET /data/{productCode}/{siteCode}/{year-month}/{filename}` → 302 redirect to the file (binary).
- `GET /data/package/{productCode}/{siteCode}/{year-month}?package=` → ZIP.
Data Query (TOKEN REQUIRED)
- `GET /data/query?productCode&siteCode(repeatable)&startDateMonth&endDateMonth&release&package&includeProvisional` and `POST /data/query` body `{productCode, siteCodes[], startDateMonth, endDateMonth, release?, package?, includeProvisional?}` → `data:{productCode, siteCodes[], startDate, endDate, packageType, releases[]({release, generationDate, packages[]({domainCode, siteCode, month, packageType, generationDate, files[]})})}`. Default excludes provisional and returns latest release.
Releases
- `GET /releases` → 253 KB list of {release, uuid, generationDate, artifacts[]({name,type:'MANIFEST_AVAILABLE',url,size,md5}), dataProducts[]}. `GET /releases/{releaseIdentifier}` (tag or uuid) → same shape; RELEASE-2025 has 114 dataProducts ({productCode, productName, productDescription, productDoi}). Also `/releases/{tag}/products`, `/releases/{tag}/products/{code}`, `/releases/{tag}/sites`, `/releases/{tag}/sites/{code}`, and token-only `/releases/{tag}/data/...` mirrors of the data endpoints.
Samples
- `GET /samples/supportedClasses` → `data.entries[]({key,value})` ~30 KB (e.g. `bet_IDandpinning_in.individualID`). `GET /samples/classes?sampleTag=` → `data.sampleClasses[]` (404 with detail text if none). TOKEN-ONLY: `GET /samples/view?(sampleTag&sampleClass)|sampleUuid|barcode|archiveGuid` → `data.sampleViews[]({sampleUuid, sampleTag, sampleClass, barcode, archiveGuid, sampleEvents[]({ingestTableName, smsFieldEntries[]({smsKey,smsValue})}), parentSampleIdentifiers[], childSampleIdentifiers[]})`; `GET /samples/download?...&degree=N` → same `views` shape, N degrees of relatedness.
Taxonomy (public)
- `GET /taxonomy?taxonTypeCode=&kingdom=&phylum=&division=&order=&class=&family=&genus=&scientificname=&verbose=&offset=&limit=&stream=` → `{count,total,prev,next,data[]}` (paginated; `next` is a full URL). taxonTypeCode enum: ALGAE, BEETLE, BIRD, FISH, HERPETOLOGY, MACROINVERTEBRATE, MOSQUITO, MOSQUITO_PATHOGENS, SMALL_MAMMAL, PLANT, TICK. taxonTypeCode must not be combined with a rank param. Item keys are Darwin-Core prefixed: taxonTypeCode, taxonID, acceptedTaxonID, updateDate, dwc:scientificName, dwc:scientificNameAuthorship, dwc:taxonRank, dwc:vernacularName, dwc:nameAccordingToID, dwc:kingdom, dwc:phylum, dwc:class, dwc:order, dwc:family, dwc:genus, dwc:specificEpithet, gbif:subspecies, gbif:variety, ... (verbose adds more ranks).
Prototype datasets (public)
- `GET /prototype/datasets` → 704 KB list; `GET /prototype/datasets/{uuid}` → {uuid, projectTitle, projectDescription, designDescription, metadataDescription, studyAreaDescription, datasetAbstract, startYear, endYear, dateUploaded, isPublished, version, versionDescription, doi:{url,generationDate}, relatedVersions[], data:{url, files[], dataLocations[]}, dataThemes[], fileTypes[], keywords[], locations[]({domain,state,siteCode,siteName,latitude,longitude}), publicationCitations[], relatedDataProducts[], scienceTeams[]}. `GET /prototype/data/{uuid}` → {datasetUuid, datasetProjectTitle, files[]({name, description, size, fileName, md5, type:{name,description}, url}), dataLocations[]}; `/prototype/data/{uuid}/{filename}` → file.
Documents
- `https://data.neonscience.org/api/v0/documents/{specNumber}` (e.g. NEON.DOC.000780vD) serves spec PDFs referenced by product `specs[].specUrl` (not in swagger; observed).
Errors
- Shape: `{"error":{"status":<int>,"detail":"<text>"},"data":null}` (403, 404 seen). 429 body is `{"message":"API rate limit exceeded"}`.

### 1.4 GraphQL (public, https://data.neonscience.org/graphql)
Query root fields (introspected): `products(release)`, `product(productCode!, release)`, `demoProduct(productCode!)`, `filterProducts(filter: DataProductFilter!)`, `sites(release)`, `site(siteCode!, release)`, `filterSites(filter: SiteFilter!)`, `location(name!)`, `locationHierarchy(name!, locationType)`, `findLocations(query: LocationQuery!)`, `prototypeDatasets`, `prototypeDataset(uuid!)`.
DataProduct fields (from docs): productCode, productName, productDescription, productScienceTeam, productPublicationFormatType, productAbstract, productHasExpanded, productBasicDescription, productExpandedDescription, themes, keywords, specs, siteCodes. GraphQL is the efficient way to fetch compact projections of products/sites instead of the 30 MB REST lists — a designer may choose it for list/search tools, but MUST keep REST as the fallback since GraphQL is documented as "metadata" only. An implementer can introspect `DataProductFilter`, `SiteFilter`, `LocationQuery` input types live before use.

### 1.5 Payload-size reality (drives tool design)
Full lists are enormous (products 30 MB, sites 27 MB). An LLM must never receive these raw. Tools must return **compact projections** (code, name, short description, team, status, site count, date range) with opt-in detail (`include_availability`, `include_specs`, `include_change_logs`, pagination/`limit`/`offset`, `fields`). Cache the parsed lists in-process (TTL ~1 h) and build in-memory indexes for search (keyword over name/description/keywords/themes; site/domain/state filters). Availability by site/month is derivable **without a token** from `/products/{code}` → siteCodes[].availableMonths / availableReleases and from `/sites/{code}` → dataProducts[].

### 1.6 Old server tool catalogue (to be superseded; keep names where sensible)
neon_list_products, neon_get_product, neon_search_products, neon_list_sites, neon_get_site, neon_search_sites, neon_get_site_products, neon_get_location, neon_list_site_locations, neon_find_towers (hard-coded tower IDs — a hack; replace with hierarchy-based lookup filtered on locationType TOWER), neon_get_location_hierarchy, neon_search_locations, neon_query_data, neon_get_download_url, neon_summarize_data_availability. Missing in old server: taxonomy, samples, releases, prototype datasets, GraphQL, documents, downloads-to-disk, citation/DOI helpers.
Old plan doc: scratchpad `neon-data-api/neon-mcp-server-plan.md`. Old source: scratchpad `neon-data-api/mcp/src/**`.

## 2. MCP 2026-07-28 — what the server must do (from the official changelog, verified)
- Stateless core: no `initialize`/`notifications/initialized`, no `Mcp-Session-Id`. Every request carries `_meta["io.modelcontextprotocol/protocolVersion"]="2026-07-28"` and `_meta["io.modelcontextprotocol/clientCapabilities"]`; clients SHOULD send `io.modelcontextprotocol/clientInfo`; servers SHOULD stamp `io.modelcontextprotocol/serverInfo` into result `_meta` (the SDK does this). Version mismatch → `UnsupportedProtocolVersionError` (-32022).
- `server/discover` is REQUIRED (SDK handles it; returns supportedVersions, capabilities, instructions, ttlMs/cacheScope).
- Streamable HTTP POST requests carry `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` headers; mismatch between header and body → `HeaderMismatchError` (-32020). SDK enforces. Single response per POST (JSON or SSE); no SSE resumability/Last-Event-ID; GET stream replaced by `subscriptions/listen` (we don't need it: our lists are static → no listChanged).
- `tools/list`, `prompts/list`, `resources/list`, `resources/read`, `resources/templates/list` results MUST carry `ttlMs` + `cacheScope` ("public"|"private") → SDK `cache_hints={"tools/list": CacheHint(ttl_ms=..., scope="public"), ...}`. Return tools in a deterministic (sorted) order.
- All results carry `resultType: "complete" | "input_required"` (SDK sets it).
- MRTR (multi round-trip): server returns `InputRequiredResult(input_requests={key: ElicitRequest(...)}, request_state=<opaque str>)`; client retries `tools/call` with `inputResponses` + `requestState`. `requestState` is client-visible/-controlled → never secrets, always re-validate. SDK offers `RequestStateSecurity` (AES-GCM codec, ttl, principal binding) for `MCPServer`. Use MRTR sparingly (e.g. disambiguating a site name or product keyword hit list) — optional for v1; document if deferred.
- Tool schemas: JSON Schema 2020-12; set `$schema: "https://json-schema.org/draft/2020-12/schema"` explicitly; `outputSchema` + `structuredContent` for structured results; `annotations` (readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=true for a remote API); `_meta` per tool allowed (e.g. `io.mesa/surface` grouping; `io.neon-mcp/requiresToken: true`).
- Deprecated (do not implement): Roots, Sampling, Logging (`logging/setLevel`, `notifications/message` unless `io.modelcontextprotocol/logLevel` in request _meta), HTTP+SSE transport, DCR. Error-code policy: -32020..-32099 reserved for spec.
- Extensions (`io.modelcontextprotocol/tasks`, apps, EMA) are optional; tasks not implemented by SDK 2.2.0 → skip.

## 3. Python SDK 2.2.0 — verified API surface (pinned facts)
Install: `mcp>=2.0,<3` (2.2.0 pulls `mcp-types==2.2.0`, pydantic>=2.12, `httpx2`, anyio, starlette, uvicorn, sse-starlette, jsonschema, opentelemetry-api). NOTE: the SDK itself uses **`httpx2`**; our NEON client can use plain `httpx` (0.28) — both can coexist.
Types are **snake_case** attributes with camelCase wire aliases: `Tool(name, title, description, input_schema, output_schema, execution=ToolExecution(task_support), icons, annotations=ToolAnnotations(read_only_hint, destructive_hint, idempotent_hint, open_world_hint), meta)` (constructor also accepts `inputSchema=`/`_meta=` aliases). `ListToolsResult(tools, next_cursor, ttl_ms, cache_scope, meta, result_type)`. `CallToolResult(content, structured_content, is_error, meta, result_type)`. `InputRequiredResult(input_requests: dict[str, ElicitRequest|...], request_state, meta)`. `ElicitRequest(method="elicitation/create", params=ElicitRequestFormParams(mode="form", message, requested_schema))`. `CallToolRequestParams(name, arguments, input_responses, request_state, task, meta)`. `Resource(name, uri: str, title, description, mime_type, size, annotations, meta)`, `ResourceTemplate(name, uri_template, ...)`, `ReadResourceResult(contents=[TextResourceContents(uri, text, mime_type)], ttl_ms, cache_scope)`, `Prompt(name, title, description, arguments=[PromptArgument(name, description, required)])`, `GetPromptResult(description, messages=[PromptMessage(role, content=TextContent(type="text", text))])`. `DiscoverResult(supported_versions, capabilities, instructions, ttl_ms, cache_scope)`. `Implementation(name, title, version, description, website_url, icons)`.
Constants: `mcp.types.LATEST_PROTOCOL_VERSION == "2026-07-28"`; `MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)`; `HANDSHAKE_PROTOCOL_VERSIONS` = 2024-11-05..2025-11-25 (SDK stays dual-era: legacy clients still work over stdio). Error codes: HEADER_MISMATCH -32020, MISSING_REQUIRED_CLIENT_CAPABILITY -32021, UNSUPPORTED_PROTOCOL_VERSION -32022, INVALID_PARAMS -32602, INTERNAL_ERROR -32603, METHOD_NOT_FOUND -32601.
Low-level server (house style, used by mesa-mcp):
```python
from mcp.server import Server, CacheHint, ServerRequestContext
from mcp import types as t
server = Server("neon-mcp", version=__version__, title="NEON Data API", instructions="...", website_url="https://github.com/idss-mesa/neon-mcp",
                cache_hints={"tools/list": CacheHint(ttl_ms=300_000, scope="public"), "resources/list": CacheHint(...), "prompts/list": CacheHint(...), "resources/read": CacheHint(...)},
                on_list_tools=async (ctx, params) -> t.ListToolsResult, on_call_tool=async (ctx, params) -> t.CallToolResult | t.InputRequiredResult,
                on_list_resources=..., on_read_resource=..., on_list_resource_templates=..., on_list_prompts=..., on_get_prompt=...)
# stdio:
from mcp.server.stdio import stdio_server
async with stdio_server() as (r, w): await server.run(r, w, server.create_initialization_options())
# streamable http (stateless):
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
mgr = StreamableHTTPSessionManager(app=server, json_response=False, stateless=True, security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=..., allowed_hosts=[...], allowed_origins=[...]), max_request_body_size=4*1024*1024)
# Starlette: Mount("/mcp", app=mgr.handle_request) inside `async with mgr.run():` lifespan; rewrite bare "/mcp" -> "/mcp/" to avoid 307 (mesa-mcp `_McpSlashNormalizer`).
```
`ServerRequestContext` exposes `request_id`, `meta`, `params`, `request` (Starlette request when over HTTP — usable to read a per-request `X-API-Token`/`Authorization` header in hosted mode). `server.create_initialization_options()` is still the capability declaration used by `server/discover` and by legacy-era stdio clients.
High-level alternative: `MCPServer(name, version=, instructions=, cache_hints=, request_state_security=RequestStateSecurity(...))` with `@mcp.tool(annotations=..., meta=..., structured_output=...)`, `mcp.streamable_http_app(stateless_http=True, json_response=..., transport_security=...)`, `mcp.session_manager.run()`. Prefer the low-level Server + our own registry (house style; full control over `_meta`, `$schema`, output schemas, deterministic ordering, conformance tests).
Testing: drive the Starlette app via `httpx.ASGITransport`; send POST /mcp with headers `MCP-Protocol-Version: 2026-07-28`, `Mcp-Method: tools/list`, `Mcp-Name: <tool>` (for tools/call), `Accept: application/json, text/event-stream`, `Content-Type: application/json`; body JSON-RPC with `params._meta` = {"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}. Port from `/Users/tswetnam/github/idss-mesa/mesa-mcp/tests/test_spec_conformance_2026_07_28.py` (class `_AppHarness`) and `tests/transport/test_streamable_http.py`. In-memory client alternative: `mcp.shared.memory` / `Client("in_memory_server", ...)`.
SDK 2.1/2.2 notes: content-block return annotations no longer advertise outputSchema (irrelevant to low-level use); sessions capped at 10 000 / idle 1800 s (irrelevant when stateless=True).

## 4. House-style references to port (read these files; do not copy blindly, adapt)
- `/Users/tswetnam/github/idss-mesa/mesa-mcp/src/mesa_mcp/server.py` — registry (`register_tool`, `ToolSpec`, `_invoke_handler`, `MesaServer._build_mcp_server`, `_tool_definitions`, MRTR `_encode_request_state`), constants `JSON_SCHEMA_DIALECT`, `TOOLS_LIST_TTL_MS`.
- `.../src/mesa_mcp/__main__.py`, `config.py` (pydantic Config + env/YAML loader, `MESA_MCP_` prefix), `errors.py` (`ToolError`, `InputRequired`), `logging.py` (structlog; stdio→stderr console, http→JSON), `context.py` (contextvars).
- `.../src/mesa_mcp/transport/streamable_http.py`, `sse.py` (Starlette app assembly, `_McpSlashNormalizer`, lifespan running the session manager), `healthz.py`.
- `.../tests/test_spec_conformance_2026_07_28.py`, `tests/transport/test_streamable_http.py`, `tests/conftest.py`, `tests/test_smoke.py`.
- `.../pyproject.toml`, `.github/workflows/ci.yml` (test matrix 3.11–3.13 + separate "MCP 2026-07-28 conformance" job that asserts `mcp` major == 2 and greps for deprecated features), `.gitignore`, `.env.example`, `CLAUDE.md`, `docs/` layout (user/dev/deploy), `.claude/agents/mcp-reviewer.md`.
- Org install conventions: `/Users/tswetnam/github/idss-mesa/docs/install.sh` registers stdio servers with `claude mcp add <name> -s user -- <abs path to venv bin> --transport stdio` (also codex/opencode/antigravity). README should show `uv tool install`/`uvx` + `claude mcp add` recipes and an HTTP recipe `claude mcp add --transport http neon https://host/mcp`.

## 5. Constraints / non-goals for v1
- Do not vendor or depend on `neonutilities` in the core (optional extra at most). The server is a thin, well-shaped API surface for agents; heavy stacking/analysis belongs to the agent's Python session.
- Downloads to local disk are allowed only in stdio mode (the process runs on the user's machine) and must be confined to a configured download directory; in HTTP mode return signed URLs instead.
- Never exceed ~50 KB per tool result by default; always paginate/truncate with explicit `truncated: true` + how to get more.
- Every tool: pydantic input model with field descriptions, output model (→ outputSchema), annotations, `_meta` (surface + requiresToken), unit test with recorded fixtures (no live network in CI), and a live smoke test marked `@pytest.mark.live` (skipped by default).

## 1.7 Additional live observations (2026-09-10, fixture recording)
- **Unknown codes return HTTP 400, not 404**: `GET /products/DP9.99999.999` → `400 {"error":{"status":400,"detail":"Product code not found"},"data":null}`; `GET /sites/ZZZZ` → 400; `GET /locations/NOPE_NOT_A_LOCATION` → 400. `GET /samples/classes?sampleTag=NOPE` → **404** with `detail` containing "No Sample Classes Found for Sample Tag: [NOPE]". Error mapping must treat 400-with-"not found"-detail as `not_found`, 400 otherwise as `invalid_argument`, 403 on token-only endpoints as `auth_required`, 404 as `not_found`, 429 as `rate_limited`, 5xx as `upstream_error`.
- GraphQL error shape: `{"errors":[{"message": "...", "locations":[{"line","column"}], "extensions":{"classification":"ValidationError"}}]}` (HTTP 200). Success shape `{"data":{...}}`.
- Extra sizes: `/releases/RELEASE-2025/products` = 25.8 MB, `/releases/RELEASE-2025/sites` = 22.2 MB, `/locations/HARV?hierarchy=true` = 1.17 MB (595 children), `/locations/HARV?hierarchy=true&locationType=TOWER` = 11.6 KB (locationType filter prunes the hierarchy → use it for tower lookup), `/locations/D01` = 766 B, `/products/DP1.10003.001` = 77 KB, `/releases/RELEASE-2025/products/DP1.00001.001` = 903 KB.
- Raw fixtures for every anonymous endpoint (plus 400/403/404 error bodies and response headers) are recorded under `scratchpad/fixtures-raw/<name>.json` + `.headers`; GraphQL introspection at `fixtures-raw/graphql_introspection.json`. Implementers shrink these into `tests/fixtures/` (keep ≤ 3 sites / ≤ 6 months / ≤ 5 items per list; keep every top-level key).
- GraphQL `DataProduct` object fields (introspected): productCode, productName, productDescription, productStatus, productScienceTeam, productPublicationFormatType, productAbstract, productHasExpanded, productBasicDescription, productExpandedDescription, themes, keywords, specs[DataProductSpec], releases[DataProductRelease], siteCodes[DataProductSite]. Full type catalogue printed in the session log; `fixtures-raw/graphql_introspection.json` has it all.

## 1.8 GraphQL filter queries — verified 2026-09-10 (token-free compact availability)
- `filterProducts(filter: {productCodes: [..]!, siteCodes: [..], startMonth: "YYYY-MM", endMonth: "YYYY-MM", release: ".."})` returns products with `siteCodes[].availableMonths` **restricted to the requested sites and month window** (3.9 KB for 2 products × 2 sites × 6 months vs ~1 MB via REST). CAVEAT: `siteCodes[].availableReleases[].availableMonths` is NOT filtered by the window (full history is returned) — project it away or clip it client-side. `filterSites(filter: {siteCodes: [..]!, productCodes: [..], startMonth, endMonth, release})` behaves the same from the site side (226 B for 1 site × 1 product × 3 months). `findLocations(query: {locationNames: [..]!})` batch-fetches locations by name (any type: SITE/TOWER/DOMAIN) with compact field selection. Fixtures: `fixtures-raw/graphql_filterProducts_availability.json`, `graphql_filterSites_availability.json`, `graphql_findLocations.json`. Full type catalogue: `scratchpad/GRAPHQL_TYPES.md`.
- Use GraphQL for: product/site list summaries (select only the fields needed → ~250 B–16 KB), availability windows, batch location lookup. Use REST for: anything GraphQL lacks (taxonomy, samples, releases, prototype data files, data/query, documents, hierarchy with locationType filter, history flag).
- Releases currently published (from /releases): RELEASE-2021 (2021-01-23, 106 products), RELEASE-2022 (2022-01-20, 109 products), RELEASE-2023 (2023-01-27, 109 products), RELEASE-2024 (2024-01-27, 109 products), RELEASE-2025 (2025-01-29, 114 products), RELEASE-2026 (2026-01-23, 136 products). Note a **RELEASE-2026** exists; docs examples that say RELEASE-2024/2025 are just examples. PROVISIONAL is a pseudo-release tag used in availableReleases.

## 1.9 Ready-made test fixtures
`scratchpad/fixtures-small/` holds 43 shrunk, hermetic JSON fixtures (every anonymous endpoint family + error bodies 400/403/404/429 + GraphQL success/error + hand-written token-only shapes `data_DP1.00001.001_ABBY_2023-01.json`, `dataquery_DP1.00001.001_ABBY.json`, `samples_view_barcode.json`, `samples_classes_ok.json`), each ≤ 40 KB, all top-level keys preserved, ≤ 3 sites / ≤ 6 months / ≤ 5 items per list. Copy them into `tests/fixtures/` as-is (file name = fixture name). Raw originals remain in `scratchpad/fixtures-raw/` if a test needs a field that was trimmed. Real signed URLs were replaced with `...X-Goog-Signature=REDACTED` in the hand-written fixtures.

## 6. Documentation site standard — OKF v0.2 bundle + Zensical + agent surface (USER REQUIREMENT, added 2026-09-10)

The user requires `docs/` to conform to the **Open Knowledge Format (OKF) v0.2** spec, render as a **Zensical** website at **https://idss-mesa.github.io/neon-mcp/** via GitHub Actions (GitHub Pages; no UNM Cascade), and expose an **agent-readable surface**: `robots.txt`, `llms.txt`, `llms-full.txt`, per-page Markdown mirror. The reference standard is https://carc.unm.edu/docs (source repo github.com/UNM-CARC/docs). This section OVERRIDES anything in a design document's "documentation" section that conflicts with it.

### 6.1 Reference material (already downloaded — copy/adapt, do not reinvent)
- OKF v0.2 spec text: `scratchpad/OKF_SPEC.md` (§4 frontmatter, §5 provenance/trust/lifecycle, §7 actor convention, §8 index files, §9 log files, §11 conformance, §12 okf_version).
- CARC docs reference files in `scratchpad/carc-docs-ref/`: `AGENTS.md`, `zensical.toml`, `docs.yml` (workflow), `okf_validate.py`, `gen_llms_txt.py`, `postbuild_agent_surface.py`, `ai-agents.md` (the agent-guide page), `README.md`.
- Live examples of the outputs: `scratchpad/carc-live/robots.txt`, `llms.txt`, `llms-full.txt`, `sitemap.xml`.
- Sibling implementations for comparison: `/Users/tswetnam/github/unm-carc.github.io/scripts/*`, `/Users/tswetnam/github/idss-mesa/docs/` (zensical.toml + CLAUDE.md docs rules), `/Users/tswetnam/github/intro-gpt/scripts/{generate_llms_txt.py,validate_okf.py}` (nav-driven variant; uses `.md` sibling convention — we use CARC's `index.md` convention instead).

### 6.2 Verified Zensical 0.0.60 behaviour (mini build in `scratchpad/ztest/`, `zensical build --clean --strict` → "No issues found")
- `zensical.toml` `[project]` keys used: `site_name`, `site_url` (MUST be `https://idss-mesa.github.io/neon-mcp/` with trailing slash — canonical links and sitemap use it), `site_description`, `site_author`, `copyright`, `repo_url`, `repo_name`, `edit_uri = "edit/main/docs/"`, `extra_css`, `nav` (inline TOML array of `{ "Title" = "path.md" }` / nested arrays), `[project.theme]` (`features`, `favicon`, `logo`, `language`, `icon.repo`), `[[project.theme.palette]]`, `[[project.extra.social]]`, `[project.markdown_extensions]` (copy CARC's list: abbr, admonition, attr_list, def_list, footnotes, md_in_html, toc.permalink, pymdownx.* incl. superfences mermaid, tabbed.alternate_style, tasklist, keys, details, emoji, highlight, inlinehilite, magiclink, smartsymbols, tilde, caret, mark, betterem).
- Output: `site/<page>/index.html` pretty URLs (`use_directory_urls` default true), `site/sitemap.xml` (+ `.gz`) with absolute sub-path URLs, `site/404.html`, `site/search.json`, `site/objects.inv` (0 bytes — delete in postbuild, as CARC does). Non-Markdown files under `docs/` (e.g. `docs/llms.txt`, `docs/assets/*`) are copied verbatim to the site root → `https://idss-mesa.github.io/neon-mcp/llms.txt`. Raw `.md` sources are NOT copied → the postbuild mirror script is required.
- Frontmatter: `description` becomes `<meta name="description">`; unknown keys (`okf_version`, `generated`, `sources`, `status`, `stale_after`, `tags`) are ignored silently even under `--strict`; a section `index.md` with no frontmatter renders fine; `title` frontmatter overrides the page title.
- Edit/view buttons resolve to `https://github.com/idss-mesa/neon-mcp/edit/main/docs/<path>.md` and `/raw/main/docs/<path>.md`.
- CLI: `zensical build [-f zensical.toml] [--clean] [--strict]`, `zensical serve`, `zensical new`. Install: `pip install zensical` (PyPI 0.0.60, requires Python ≥ 3.10). No plugin/hook system needed — all agent-surface work is done by our scripts before/after the build.

### 6.3 Bundle rules (OKF v0.2, as enforced by `scripts/okf_validate.py`)
- Every non-reserved `docs/**/*.md` MUST start with a YAML frontmatter block containing a non-empty `type`. House `type` vocabulary for neon-mcp: `Homepage` is NOT used (root index is reserved); use `Guide`, `Tutorial`, `Reference`, `Policy`, `MCP Tool Reference`, `Log`-free (log.md has no frontmatter).
- Recommended keys on every content page, in this order:
  ```yaml
  ---
  title: "Install neon-mcp"
  description: "One sentence, 50–160 chars, plain text; becomes the meta description and the llms.txt entry."
  type: Guide
  tags:
    - install
    - uv
  generated:
    by: "claude/fable-5.1"            # actor convention §7: <producer>/<version>; humans are human:<id> (e.g. human:tswetnam)
    at: "2026-09-10T00:00:00Z"        # ISO 8601 with Z; bump on meaningful content change
  sources:                            # load-bearing external references, keyed by id for footnote attribution [^id]
    - id: neon-api-auth
      resource: "https://data.neonscience.org/data-api/authentication/"
      title: "NEON Data API — Authentication"
      author: "team:neon"
    - id: mcp-spec
      resource: "https://modelcontextprotocol.io/specification/2026-07-28"
      title: "MCP specification 2026-07-28"
      author: "team:modelcontextprotocol"
  status: stable                      # draft | stable | deprecated (absent ⇒ stable)
  stale_after: "2027-03-10T00:00:00Z" # only on pages stating facts NEON/MCP may change (rate limits, token rules, SDK versions)
  ---
  ```
  NEVER add `verified:` — only a human (`human:tswetnam`) may add `verified: { by: "human:tswetnam", at: ... }`.
- Section `index.md` files (`docs/<section>/index.md`) carry NO frontmatter: a `# Heading` then bullet listings `* [Title](page.md) - description` (progressive disclosure, §8). Zensical renders them as section landing pages (enable `navigation.indexes` and list them as `{ "Contents" = "<section>/index.md" }` first in each nav group, as CARC does).
- Root `docs/index.md` (Zensical homepage) carries ONLY `okf_version: "0.2"`, `title`, `description` in frontmatter (validator tolerates `hide`/`icon` too) and a body that is both a landing page and an OKF bundle listing (link every section with a one-line description).
- `docs/log.md`: no frontmatter; `# Directory Update Log`; `## YYYY-MM-DD` headings newest first; bullets `* **Creation**: …` / `* **Update**: …` / `* **Deprecation**: …`. Add an entry for every substantive docs change (the initial entry: 2026-09-10 Creation of the bundle).
- Links: internal links relative and plain (`install.md`, `../tools/products.md`); external links get `{target=_blank}` (attr_list). Code in fenced blocks with a language. Images under `docs/assets/` referenced as relative paths.

### 6.4 Files to create (docs work package owns ALL of these)
```
zensical.toml                          site config: site_url https://idss-mesa.github.io/neon-mcp/, repo idss-mesa/neon-mcp, nav below, CARC theme features, palette (primary "green", accent "teal" like idss-mesa/docs or custom NEON-ish), social link github.com/idss-mesa
docs/index.md                          root (okf_version "0.2")
docs/log.md                            OKF change log
docs/llms.txt, docs/llms-full.txt      GENERATED by scripts/gen_llms_txt.py and COMMITTED (CI fails on drift)
docs/getting-started/index.md          section listing (no frontmatter)
docs/getting-started/install.md        uv tool install / uvx / pipx / from source; verify with neon-mcp --version
docs/getting-started/quickstart.md     first session: claude mcp add … ; neon_ping; find a product; check availability
docs/getting-started/api-token.md      why (403 on data endpoints since 2026-06), where to get it (myaccount), NEON_MCP_NEON__API_TOKEN, header/query forms, never commit it; rate limits table (stale_after set)
docs/getting-started/clients.md        Claude Code, Claude Desktop, Codex CLI, OpenCode, Antigravity, generic JSON (stdio) + hosted HTTP (`claude mcp add --transport http neon https://host/mcp`)
docs/getting-started/configuration.md  full config reference: YAML, env vars (NEON_MCP_SECTION__FIELD), CLI flags, precedence
docs/tools/index.md                    section listing
docs/tools/reference.md                FULL tool reference, GENERATED from the registry by scripts/gen_tools_reference.py (name, description, input params table from pydantic schema, output fields, endpoint, requiresToken, annotations); committed; CI fails on drift
docs/tools/<family>.md                 one narrative page per family: products, sites, locations, availability-and-data, releases, taxonomy, samples, prototype-datasets, graphql, utilities — when to use which tool, worked examples, pitfalls (payload sizes, provisional data, release tags)
docs/tools/resources-and-prompts.md    MCP resources (neon://…) and prompts the server exposes
docs/mcp/index.md                      section listing
docs/mcp/spec-2026-07-28.md            how neon-mcp implements the stateless core: server/discover, _meta envelope, cache hints, resultType, MRTR/requestState rules, header routing, no deprecated features; conformance test list
docs/mcp/transports.md                 stdio vs Streamable HTTP (/mcp, /healthz), TransportSecuritySettings, per-request token passthrough header in HTTP mode
docs/deploy/index.md                   section listing
docs/deploy/hosted-http.md             uvicorn behind nginx/Caddy, systemd unit, env file, health checks, horizontal scaling (stateless)
docs/deploy/security.md                token handling, logging redaction, DNS-rebinding protection, download-directory confinement
docs/develop/index.md                  section listing
docs/develop/architecture.md           module map, registry/adapter, client/cache/projection layers (mermaid diagram)
docs/develop/adding-tools.md           @register_tool walkthrough with a real tool; output models; annotations; fixture + test
docs/develop/testing.md                pytest layout, fixtures, respx/httpx mocking, `live` marker, conformance suite
docs/develop/contributing.md           branch/PR rules, ruff/mypy, log.md + llms regeneration, versioning, release process (tag → PyPI optional)
docs/about/index.md                    section listing
docs/about/ai-agents.md                agent guide (adapt carc-docs-ref/ai-agents.md: endpoints table with our URLs, OKF frontmatter reading guide, trust tiers, "cite the page URL", pointer to source repo + AGENTS.md)
docs/about/citing-neon.md              NEON data policy (CC-BY 4.0), how to cite products/releases with DOIs, provisional-data caveats, acknowledging NEON/NSF; links to NEON policy pages
docs/about/license.md                  MIT for the server; CC-BY-4.0 note for the docs content (optional; if omitted, state license in index)
docs/assets/                           favicon/logo (simple SVG; do not hotlink NEON logos)
docs/stylesheets/extra.css             optional small theme tweaks
scripts/okf_validate.py                copy of carc-docs-ref/okf_validate.py (identical logic; update docstring/usage)
scripts/gen_llms_txt.py                adapt carc-docs-ref/gen_llms_txt.py: SECTION_ORDER = getting-started, tools, mcp, deploy, develop, about; header text describes neon-mcp; site_url read from zensical.toml; writes docs/llms.txt + docs/llms-full.txt
scripts/postbuild_agent_surface.py     adapt carc-docs-ref/postbuild_agent_surface.py: same mirror (page URL + index.md), same <head> injection (robots meta, alternate text/markdown, okf:* meta), same robots.txt (AI-agent allow list + Sitemap + pointers to llms.txt, llms-full.txt, about/ai-agents/), delete 0-byte objects.inv; base URL from zensical.toml
scripts/gen_tools_reference.py         NEW: imports neon_mcp registry (no network), renders docs/tools/reference.md deterministically (sorted by tool name) with OKF frontmatter (type: Reference, generated.by "process:gen_tools_reference", generated.at fixed from the latest git commit date or a CLI flag — must be reproducible so CI drift check is stable; do NOT stamp wall-clock time)
.github/workflows/docs.yml             two jobs, adapted from carc-docs-ref/docs.yml WITHOUT the publish-cascade job:
                                         okf-conformance: checkout@v7, setup-python@v6 (3.x), pip install -e ".[docs]" (or `pip install pyyaml zensical` + package), python scripts/okf_validate.py docs, python scripts/gen_llms_txt.py && python scripts/gen_tools_reference.py && git diff --exit-code docs/llms.txt docs/llms-full.txt docs/tools/reference.md
                                         deploy (needs okf-conformance; if: github.event_name != 'pull_request'): environment github-pages, configure-pages@v6 with enablement: true, checkout@v7, setup-python@v6, pip install zensical pyyaml (+ package if reference gen runs here), zensical build --clean --strict, python scripts/postbuild_agent_surface.py site, upload-pages-artifact@v5 (path: site), deploy-pages@v5 (id: deployment)
                                         triggers: push to main, pull_request, workflow_dispatch; permissions contents: read, pages: write, id-token: write; concurrency group pages
AGENTS.md                              repo-root agent guide (adapt carc-docs-ref/AGENTS.md): what the repo is, reading the corpus (llms.txt paths), commands (uv sync, pytest, ruff, zensical serve/build, the three scripts), editing rules (frontmatter required, index.md no frontmatter, log.md entries, regenerate llms + tools reference, never add verified:)
CLAUDE.md                              project guide (house style from mesa-mcp CLAUDE.md) + a "Docs follow OKF v0.2" section that mirrors idss-mesa/docs CLAUDE.md rules and points to AGENTS.md
pyproject.toml                         add optional-dependency group `docs = ["zensical>=0.0.60", "pyyaml"]`
README.md                              link to the docs site, the agent surface (llms.txt), and AGENTS.md
```
Nav (zensical.toml) order: Home · Getting started · Tools · MCP protocol · Deploy · Develop · About (About group includes `about/ai-agents.md`, `about/citing-neon.md`, and `log.md` as "Changelog").

### 6.5 Acceptance criteria for the docs work package
1. `python scripts/okf_validate.py docs` → 0 errors (warnings allowed only for the root index's extra keys).
2. `python scripts/gen_llms_txt.py && python scripts/gen_tools_reference.py && git diff --exit-code docs/llms.txt docs/llms-full.txt docs/tools/reference.md` → clean.
3. `zensical build --clean --strict` → "No issues found"; `python scripts/postbuild_agent_surface.py site` mirrors every page; `site/robots.txt`, `site/llms.txt`, `site/llms-full.txt`, `site/sitemap.xml` exist; `site/<page>/index.md` exists for every page; `grep 'okf:type' site/getting-started/install/index.html` matches.
4. Every content page has `type`, `title`, `description`, `tags`, `generated`, `sources`; no page has `verified`.
5. `docs/log.md` has the 2026-09-10 creation entry; `docs/about/ai-agents.md` lists the exact URLs under https://idss-mesa.github.io/neon-mcp/.
6. `.github/workflows/docs.yml` passes `actionlint`-level sanity (valid YAML, action versions as listed) and would deploy to the `github-pages` environment on first push to main (Pages enablement is automatic via configure-pages `enablement: true`).

## 3.1 SDK 2.2.0 addendum — simplest Streamable HTTP wiring (verified by reading the source)
The low-level `mcp.server.Server` has `streamable_http_app(*, streamable_http_path="/mcp", json_response=False, stateless_http=False, event_store=None, retry_interval=None, max_request_body_size=4 MiB, session_idle_timeout=1800, max_sessions=10000, transport_security=None, host="127.0.0.1", auth=None, token_verifier=None, auth_server_provider=None, custom_starlette_routes=None, debug=False) -> Starlette`. It builds the `StreamableHTTPSessionManager(app=self, stateless=stateless_http, ...)`, mounts it at `streamable_http_path` as a `Route` (so `/mcp` works without a trailing-slash rewrite), appends `custom_starlette_routes` (put `GET /healthz` here), and returns `Starlette(routes=..., lifespan=lambda app: session_manager.run())` — i.e. the lifespan is already wired; serve it with `uvicorn.Server(uvicorn.Config(app, host, port, lifespan="on")).serve()`. When `transport_security is None` and host is loopback it auto-enables DNS-rebinding protection for localhost only; for a public bind pass `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[...], allowed_origins=[...])` explicitly (or `enable_dns_rebinding_protection=False` behind a reverse proxy that normalises Host). `server.session_manager` is available after the call. Prefer this over mesa-mcp's hand-built Starlette app unless a middleware (e.g. per-request NEON token header extraction) is needed — in that case wrap the returned app in a raw ASGI middleware that reads `X-NEON-API-Token`/`Authorization` and sets a contextvar (mesa-mcp OIDCMiddleware pattern, without OIDC).
