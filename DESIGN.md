# neon-mcp — FINAL design (synthesis of the three lens designs)

Status: **implementation-ready, 2026-09-10.** Target: MCP **2026-07-28** (stateless core) on the Python `mcp` SDK 2.x (`mcp>=2.0,<3`; 2.2.0 current), Python 3.11+. Repo `https://github.com/idss-mesa/neon-mcp`, package `neon_mcp`, console script `neon-mcp`, tool prefix `neon_`, MIT (Regents of UNM). Everything in RESEARCH.md §0 is taken as decided and not reopened.

Provenance: the spine is the **api-fidelity** design (winner). Grafted from **agent-ergonomics**: fuzzy resolution with `resolved`/`didYouMean`/`ambiguous_input`, `nextSteps` on every result, the unified `neon_list_files`, batch `neon_download_files` with plan-before-transfer, `fit_to_budget`, `MonthRanges`, opt-in `include[]` detail sections, the tiny ping probe, strict mypy, the tools/list size test. Grafted from **operations-conformance**: `Token` model with TLS gate and `share_config_token_over_http=false`, per-identity rate limiter, `io.neon-mcp/upstream` result `_meta`, `FixtureRouter` with unexpected-call assertions, `/readyz` + prewarm + GraphQL circuit breaker, request-id middleware, `--check`, `gen_config_reference.py`, key-set drift live tests, stdio dual-era test, `detail` planner modes. Section 9 implements RESEARCH §6 (the documentation standard that overrides every design's §9) and reconciles with the phase-1 docs scaffold that already exists in `/Users/tswetnam/github/neon-mcp` (zensical.toml, docs/index.md, docs/log.md, getting-started/api-token.md, about/*, the three CARC-derived scripts, docs.yml — all carrying `TODO(phase-2)` markers this design resolves).

Sections 1–10 are the ten sections required of the designers; §11 adds the implementation work packages, §12 the fixture plan.

---

## 0. Decisions register (every contradiction the judges flagged, decided once)

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Wire naming | **Inputs**: snake_case advertised in `inputSchema`; every field also accepts NEON's camelCase spelling (`product_code` ⇐ `productCode`, `start_month` ⇐ `startMonth`/`startDateMonth`) via `AliasChoices`. **Outputs**: NEON's own camelCase keys verbatim wherever a NEON field exists (`productCode`, `siteCode`, `dwc:scientificName`, `availableReleases`); fields neon-mcp adds are camelCase (`nextSteps`, `page.nextOffset`, `monthRange`). | House style (mesa-mcp) for inputs; NEON fidelity + continuity with the old server for outputs; an agent that copies a value from a result into an argument always validates. |
| D2 | One month-window name | `start_month` / `end_month` on **every** tool (`neon_get_availability`, `neon_list_files`, `neon_download_files`, `neon_search_products.available_from/available_to` are the only exceptions and are range-overlap filters, not windows). `end_month` defaults to `start_month`. Aliases accepted: `startMonth`, `endMonth`, `startDateMonth`, `endDateMonth`. | api-fidelity used three names for the same thing. |
| D3 | Download tool | One batch tool `neon_download_files` (≤ 50 files / 2 GiB per call, plan computed **before** any byte moves), `if_exists: "skip" \| "error"` (no overwrite mode at all), `destructiveHint=false`, `readOnlyHint=false`, `idempotentHint=true`. stdio only, absent from the HTTP `tools/list`. | Batch is the fewest-calls story; dropping overwrite makes `destructiveHint=false` honest (judges: "set true or drop overwrite"). |
| D4 | Data listing | One tool `neon_list_files` that picks `GET /data/{p}/{s}/{m}` (single site-month) or `POST /data/query` (anything else) automatically, with `detail: "files" \| "site_months" \| "summary"` planner modes and filename-grammar filters (`kind`, `table`, `hor`, `ver`, `tmi`). No separate `neon_query_data`. | agent-ergonomics unification + operations-conformance planner modes. |
| D5 | Availability source | GraphQL `filterProducts`/`filterSites` always (also with no filters: `filterProducts(filter:{productCodes:[code]})`), `availableReleases[].availableMonths` **clipped locally** to the window; REST detail fallback with local filtering. | RESEARCH §1.8; 3.9 KB vs 1 MB. |
| D6 | `release="PROVISIONAL"` | Rejected locally by the `ReleaseTag` type (`^RELEASE-\d{4}$`) with a message naming the right switch. Provisional handling is a separate input everywhere: `provisional: include\|exclude\|only` (availability), `include_provisional: bool` (files/downloads), `provisional: bool` (citation). Never sent upstream. | Verified upstream 400 / `BadRequestGraphQLException`. |
| D7 | 400 mapping | 400 whose `detail` matches `/not found/i` → `not_found` (with `validReleases` copied from `data.validReleases` when present); other 400 → `invalid_argument`; 404 → `not_found`; 403 → `auth_required` (no token) / `forbidden` (token sent); 429 → `rate_limited`; 5xx → `upstream_error`; transport/timeouts → `upstream_unavailable`. | RESEARCH §1.7. |
| D8 | Size enforcement | `fit_to_budget` (agent-ergonomics): pop items from the model's `budget_list` tail, eliding `budget_elide_fields` (URLs) first, set `page.truncated=true`, `page.truncatedReason="budget"`, append a `nextSteps` line. Last-resort guard: payload still > `limits.hard_max_result_bytes` (200 000) → `result_too_large` error (a test asserts it never fires on fixtures). | Brief §5 wants truncation, not errors. |
| D9 | Token on public endpoints | `neon.token_for_public_endpoints: bool \| None = None` → auto **true on stdio** (single user, 2000/8 rps tier), **false on http** (the operator token is never spent for anonymous callers; per-request header tokens go only to token endpoints). Public-endpoint responses are identical with/without a token, so cache keys for public endpoints never include a token scope; token-endpoint entries are keyed by `Token.identity()`. | Both judges: decide explicitly; B safest hosted, A/C right for stdio. |
| D10 | HTTP header token gate | Header `X-API-Token` (NEON's own name, configurable), honoured only when `server.public_base_url` is `https://` **or** `server.allow_insecure_header_token=true`; `share_config_token_over_http=false` by default; **no** `Authorization: Bearer` (collides with MCP OAuth semantics). | operations-conformance gates + NEON header name. |
| D11 | Rate limiting | Per-identity token buckets (`anon`, `tok:<sha256[:12]>`), 10 % under NEON (anon 180 burst / 1.8 rps; token 1800 / 7.2 rps), `observe()` re-sync from `X-RateLimit-*`, low-water pre-wait, `penalize()` on 429, one process-wide semaphore (4). | B keying + C margin. |
| D12 | HTTP app | `Server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, custom_starlette_routes=[/healthz, /readyz], transport_security=…)` + **one** raw ASGI `RequestContextMiddleware` (request id + token header + contextvars). No slash normaliser, no mutation of Starlette internals: client/catalog/prewarm lifecycle is owned by `serve_http()` around `uvicorn.Server.serve()` (and by the same `app_lifecycle()` context manager in tests). | RESEARCH §3.1; judge flagged `app.router.lifespan_context` mutation as fragile. |
| D13 | MRTR | Only `neon_get_sample` elicits (sample-class disambiguation, verifiable candidate list from the public `/samples/classes`), gated on `clientCapabilities.elicitation`; otherwise `ambiguous_input`. Fuzzy product/site resolution **never elicits**: a confident match is used and echoed in `resolved[]`, otherwise `ambiguous_input` with ≤ 8 candidates (ranked lists beat elicitation for LLM callers). The conformance suite registers a test-only MRTR tool so encode/decode/tamper/expiry paths are exercised regardless. | C scope + A fallback + B test-only tool. |
| D14 | Health | `/healthz` (liveness, no cache/upstream inspection) and `/readyz` (503 while prewarming, `degraded: true` if prewarm failed, catalog warmth, `tokenConfigured`). | B's split. |
| D15 | Docs | RESEARCH §6 wholesale (OKF v0.2 bundle, Zensical, agent surface), extending the phase-1 scaffold already on disk. | Brief §6 overrides. |
| D16 | Fixtures | The 43 `fixtures-small/` files copied verbatim + B's `FixtureRouter` (fails on unexpected upstream calls, asserts `X-API-Token` on token endpoints) + the hand-written additions in §12. | RESEARCH §1.9. |
| D17 | mypy | `mypy --strict src/` on every module, no `continue-on-error`. | Greenfield repo. |
| D18 | Token env aliases | Documented name `NEON_TOKEN` (the variable NEON's tutorials and neonutilities examples use; neither package reads it automatically); `NEON_MCP_NEON__API_TOKEN` overrides it. `NEON_API_TOKEN` is **not** read (no NEON source uses it); the loader warns when it is the only one set. | Fix A's unverified claim; amended 2026-09-11 to drop the unsourced alias. |
| D19 | tools/list size | Conformance test asserts `len(json.dumps(tools/list))` ≤ `limits.tools_list_max_bytes` (initial 48 000) **and** every description ≤ 600 chars ending in a "Next:" sentence. The integration package (§11 WP9) measures the real figure with pydantic `$defs`, records it in `docs/mcp/spec-2026-07-28.md`, and tightens the threshold to `ceil(measured × 1.25)`. | A's assertion; measure before fixing. |
| D20 | Tool names (final) | `neon_get_availability`, `neon_find_locations`, `neon_list_files`, `neon_list_sample_classes`, `neon_download_files`; no aliases in v1. Prompts keep the `neon_` prefix. | One set. |
| D21 | Extras | `pdf=["pypdf>=4"]`, `docs=["zensical>=0.0.60","pyyaml"]`, `dev=[…]`. No `crc32c` extra (crc32c is passed through from listings, never computed); no doi.org negotiation (BibTeX rendered locally). | Brief-mandated `docs` extra; drop speculative deps. |
| D22 | Ping probe | `GET /taxonomy?taxonTypeCode=TICK&limit=1` (~1 KB), never `GET /releases` (253 KB). | A. |
| D23 | Citation wording | NEON's published form, rendered from the `neon://guide/citing-neon-data` resource whose docs twin (`docs/about/citing-neon.md`) cites the NEON data-policy page in OKF `sources`: `NEON (National Ecological Observatory Network). {productName} ({productCode}), {release}. {doiUrl}. Dataset accessed from https://data.neonscience.org on {Month D, YYYY}.` Provisional: `… ({productCode}), provisional data. Dataset accessed from https://data.neonscience.org on {Month D, YYYY}. Data archived at [your DOI].` | A's order (closest to NEON); C's "accessed from productDoi.url" was wrong. |
| D24 | Month-range wire form | ISO-8601 interval string, always a pair: `"2016-04/2017-12"`; a single month is `"2016-04/2016-04"`. | One grammar, regex-friendly. |
| D25 | Surface enum | 10 values: `core, catalog, locations, data, releases, taxonomy, samples, prototype, documents, graphql`. Docs family pages (brief §6.4) are a separate, hand-written grouping. | A/B. |
| D26 | Hierarchy walks | `location_type` is **required** when the root is `REALM` or a domain (`D01`–`D20`); a SITE root without `location_type` is allowed (one cached 1.17 MB fetch, never an extra call), `typesAvailable` is computed from that same payload; when `location_type` is given, `typesAvailable` is `null` and `notes` points at `neon://reference/vocabularies`. `/locations/REALM?hierarchy=true` unfiltered is never requested. | Payload hazard; B's guard; A's `types_available` without extra calls. |
| D27 | `/data/query` bound | `sites × months ≤ limits.max_site_months_per_query` (500) else `query_too_large` with the count and how to narrow; the integration package measures real `POST /data/query` sizes live before 0.1.0 and adjusts the default. | Unbounded in all three designs. |
| D28 | Provisional defaults | Consistent **include**: `neon_get_availability.provisional="include"`, `neon_list_files.include_provisional=true`, `neon_download_files.include_provisional=true`. Every file row carries `release` (`PROVISIONAL` or a tag); `notes` says how many site-months are provisional and how to exclude them; `neon_get_citation` switches to the provisional wording when asked. | So what availability shows is what listing returns. |
| D29 | 22.2 MB / 25.8 MB mirrors | `neon_get_release(include=["sites"])` uses the GraphQL `sites(release:)` codes-only query (~200 KB); `/releases/{tag}/sites` and `/releases/{tag}/products` are documented as intentionally unused (payload hazard). `/releases/{tag}/products/{code}` and `/releases/{tag}/sites/{code}` remain reachable via `neon_get_release(product_code= / site_code=)`. No `release_path_style` option; `?release=` everywhere. | Payload hazard; drop C's mirror retry. |
| D30 | Product detail default | `include: list[…] = []` — base record ≈ 4 KB served from the warm catalog (which selects `releases{productDoi}` + `specs`), REST detail only when a section needs it. | C's ~30 KB default was the heaviest. |
| D31 | Document text extraction | In memory, both transports, ≤ 25 MiB, paged by `char_offset`/`max_chars`; never a temp file. | Brief §5 (disk only on stdio). |
| D32 | Resource-not-found | JSON-RPC `-32602` with `data={"code":"not_found","didYouMean":[…]}`; there is no `-32002` in `mcp.types` and `McpError` is an SDK-1.x idiom — the integration package confirms the 2.x exception class from mesa-mcp's current `server.py`. | Judge's SDK verification. |
| D33 | `protocolVersion` literals | Always `mcp.types.LATEST_PROTOCOL_VERSION`, never a hard-coded string. | Missed by all three. |
| D34 | `format` keywords | Not stripped from schemas (`format` is valid 2020-12 annotation vocabulary). | Judge. |

Factual corrections applied against RESEARCH.md: six releases exist (RELEASE-2021…RELEASE-2026), not "~8"; no `AER` science team (TIS 56 + TOS 42 + AOP 41 + AOS 40 + AIS 23 = 202); taxonomy "400 no data → empty" is unverified and **not** asserted (an empty page is `count: 0`); `mcp>=2.0,<3` (not `>=2.2`); the 3.2 MB catalog figure is the api-fidelity design-pass probe (not "RESEARCH §3.7"; the scratchpad's `gql_products.json`, without `releases`/`specs`, is 3.15 MB) and is re-measured in WP9; HARV's hierarchy has **595** top-level children / 1.17 MB (not "~9 000 nodes"); `neon_get_product(include=[])` can be served from the catalog **because** the catalog query selects `releases{productDoi}` and `specs` (A's index did not); `neon_download_files` carries `requiresToken: true` with `token_check="handler"` so prototype/document selectors work without a token while the `/data/**` selector fails fast; `-32020` is header/body mismatch, `-32022` is unsupported protocol version.

---

## 1. Tool catalogue

### 1.1 Conventions that apply to every tool

* **Input models** subclass `NeonInput` (`models/common.py`): `extra="forbid"` (an unknown field → `invalid_argument` naming the field and listing valid ones), `populate_by_name=True`, `alias_generator=AliasGenerator(validation_alias=lambda n: AliasChoices(n, to_camel(n)))` so snake_case is what the schema advertises (pydantic uses the first choice) and camelCase is accepted. Extra aliases where NEON's spelling differs: `class_` ⇐ `class`; `scientific_name` ⇐ `scientificname`, `scientificName`; `start_month`/`end_month` ⇐ `startDateMonth`/`endDateMonth`. Every field has a `description` (it becomes the schema text the agent reads).
* **Output models** subclass `ToolResultBase` (`NeonOutput` + envelope): serialised `by_alias=True, exclude_none=True, mode="json"`. Envelope on every result: `resolved: [Resolved]` (echo of fuzzy resolutions: `{field, input, code, confidence}`), `notes: [str]` (human-readable caveats: provisional data, clipping, fallback used), `nextSteps: [str]` (1–3 concrete follow-up calls as text), `source: {endpoints: [str], via: "graphql"|"rest"|"local"|"mixed", cached: bool, derived: [str]}`.
* **Codes are tolerant.** A field named `product` accepts `DP1.10003.001`, `DP1.10003` (→ `.001`), `NEON.DP1.10003.001` or a fuzzy name (`"breeding landbird"`); `site` and each element of `site_codes` accept `HARV`, `harv` or `"Harvard Forest"`. Resolution (`neon/resolve.py`): exact-code fast path → catalog fuzzy candidates → accept only if `score ≥ 0.75 and (single candidate or score ≥ 1.15 × runner-up)`, echoed in `resolved[]`; otherwise `ambiguous_input` (`details.candidates` ≤ 8 `{code, label, score}`); none → `not_found` with `details.didYouMean`. Fields named `*_code` (e.g. `product_code` in `neon_get_release`) are strict patterns, no fuzzy logic.
* **Shared input types** (`models/common.py`): `ProductCode = ^DP[0-4]\.\d{5}\.\d{3}$`; `SiteCode = ^[A-Z]{4}$` after a `BeforeValidator(str.upper)`; `Month = ^\d{4}-(0[1-9]|1[0-2])$` (and ≥ `2012-01`); `ReleaseTag = ^RELEASE-\d{4}$` (custom error: "PROVISIONAL is not a release; use the `provisional`/`include_provisional` switch"); `ReleaseId = ReleaseTag | uuid | "latest"`; `DomainCode = ^D(0[1-9]|1\d|20)$`; `PackageType = Literal["basic","expanded"]`; `TaxonTypeCode` (11 values); `SpecNumber = ^NEON\.DOC\.\d{6}(v[A-Z]{1,2})?$`; `Uuid` (36-char); `LocationName` (1–200 chars, case-sensitive).
* **Pagination**: every list carries `page: {total: int|null, returned, offset, limit, truncated, nextOffset: int|null, truncatedReason: "limit"|"budget"|null}`; `limit` defaults per tool, clamped to `limits.max_limit` (500).
* **Result budget**: `limits.max_result_bytes` (50 000) on the compact JSON, enforced generically by `registry.fit_to_budget` (§4.10) after the handler returns; text and `structuredContent` carry the same compact JSON (`separators=(",",":")`, `ensure_ascii=False`).
* **Descriptions** ≤ 600 chars, end with a "Next:" sentence naming the natural follow-up; long guidance lives in resources.
* **Token semantics**: `requires_token=True` tools fail with `auth_required` **before** any request when no token is available (`token_check="registry"`); `neon_download_files` uses `token_check="handler"` (only its `/data/**` selector needs a token).
* **Annotations**: all tools `readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=true` except `neon_download_files` (`readOnlyHint=false`).
* **Per-tool `_meta`**: `io.neon-mcp/surface`, `io.neon-mcp/requiresToken: bool`, `io.neon-mcp/endpoints: [str]` (feeds `gen_tools_reference.py`), and `io.neon-mcp/stdioOnly: true` on `neon_download_files`.
* **Result `_meta`** (adapter, every `CallToolResult`): `io.neon-mcp/upstream = {requests, cacheHits, rateLimitRemaining, rateLimitLimit, identity: "anonymous"|"token"}`, merged into the SDK-stamped `_meta` (a test asserts both `io.modelcontextprotocol/serverInfo` and ours are present).
* **Ordering**: `tools/list` sorted by name, fixed per deployment (transport + `downloads.enabled` decide whether `neon_download_files` is present); the list is per-deployment, not per-caller, so `cacheScope: "public"` is honest.

### 1.2 Master table (20 tools; 19 in HTTP mode), in `tools/list` order

| # | Tool | One line | Required inputs | Output model | NEON endpoint(s) | Token | Surface | Default limit | Truncation |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `neon_download_files` | Batch-download data files / month ZIPs / prototype files / documents into the confined download directory (stdio only) | one selector group (§1.3) | `DownloadReport` | `GET /data/{p}/{s}/{m}[/{filename}]`, `GET /data/package/…`, `POST /data/query`, `GET /prototype/data/{uuid}[/{filename}]`, `GET /documents/{spec}` | y (`/data/**` only) | data | 50 files / 2 GiB | plan refuses before transfer |
| 2 | `neon_find_locations` | Descendants of a site/domain/REALM/location filtered by `locationType` (TOWER, HUT, MEGAPIT, …), with coordinates | `root` xor `site_codes` | `LocationList` | `GET /locations/{root}?hierarchy=true[&locationType=]`, `GET /locations/sites`, GraphQL `findLocations` | n | locations | 50 (max 200) | page |
| 3 | `neon_get_availability` | Site×month (or product×month) availability as month ranges, per release incl. PROVISIONAL, optionally windowed — no token | `product` and/or `site` | `AvailabilityMatrix` | GraphQL `filterProducts`/`filterSites`; REST `GET /products/{code}`, `GET /sites/{code}` fallback | n | catalog | 100 rows (max 500) | page |
| 4 | `neon_get_citation` | NEON-format citation text + BibTeX + DOI for a product release, provisional data, or a prototype dataset | `product` xor `prototype_uuid` | `Citation` | `GET /products/{code}`, `GET /releases/{id}`, `GET /prototype/datasets/{uuid}` | n | releases | — | — |
| 5 | `neon_get_document` | Metadata (and optionally extracted text) of a NEON document (ATBD, protocol, user guide) | `spec_number` xor `url` | `Document` | `HEAD/GET /documents/{spec}`; spec index from catalog | n | documents | 20 000 chars | `textTruncated`, `nextCharOffset` |
| 6 | `neon_get_location` | One named location in depth (coordinates, UTM, properties, history, parent chain, pruned children) | `name` | `LocationDetail` | `GET /locations/{name}?history=&hierarchy=&locationType=` | n | locations | children 50 (max 500) | `childrenTruncated`, `historyTruncated` |
| 7 | `neon_get_product` | One product with opt-in sections (abstract, design, specs, releases/DOIs, change logs, availability, biorepository) | `product` | `ProductDetail` | catalog; `GET /products/{code}?release=` | n | catalog | change logs 25 (max 200) | `changeLogsPage`, `*Truncated` |
| 8 | `neon_get_prototype_dataset` | One prototype dataset with files and signed URLs | `uuid` | `PrototypeDatasetDetail` | `GET /prototype/datasets/{uuid}`, `GET /prototype/data/{uuid}` | n | prototype | files 100 (max 500) | `filesPage` |
| 9 | `neon_get_release` | One release: products + DOIs, sites (codes/names), artifacts; or one product/site as published in that release | `release` | `ReleaseDetail` | `GET /releases/{id}`, GraphQL `sites(release:)`, `GET /releases/{tag}/products/{code}`, `GET /releases/{tag}/sites/{code}` | n | releases | products 50 (max 500) | `productsPage` |
| 10 | `neon_get_sample` | Sample custody chain by tag+class / UUID / barcode / archiveGuid, optional N-degree relatives | one identifier mode | `SampleViews` | `GET /samples/view`, `GET /samples/download?degree=`, public `GET /samples/classes` | **y** | samples | 20 views (max 100) | page, `eventsTruncated` |
| 11 | `neon_get_site` | One site with product availability rows, releases, optional location record | `site` | `SiteDetail` | `GET /sites/{code}?release=`, `GET /locations/{siteCode}` | n | catalog | products 100 (max 300) | `productsPage` |
| 12 | `neon_graphql` | Guard-railed read-only GraphQL escape hatch | `query` xor `introspect_type` | `GraphQLResult` | `POST /graphql` | n | graphql | 50 000 B (max 200 000) | largest list pruned, `truncatedPaths` |
| 13 | `neon_list_files` | Data files (+ signed URLs) for product × sites × months; auto-selects single-cell GET or `POST /data/query`; planner modes | `product`, `site_codes`, `start_month` | `FileListing` | `GET /data/{p}/{s}/{m}[/{filename}]`, `POST /data/query` | **y** | data | 50 files (max 200) | URLs elided first, then page |
| 14 | `neon_list_releases` | All releases (six today) with dates, product counts, manifest artifacts | — | `ReleaseList` | `GET /releases` | n | releases | all | — |
| 15 | `neon_list_sample_classes` | Supported sample classes, or the classes a `sample_tag` belongs to | — | `SampleClassList` | `GET /samples/supportedClasses`, `GET /samples/classes?sampleTag=` | n | samples | 50 (max 500) | page |
| 16 | `neon_ping` | Liveness + capability report (token configured, downloads, catalog warmth, rate-limit headroom) | — | `PingResult` | none; `GET /taxonomy?taxonTypeCode=TICK&limit=1` when `check_api` | n | core | — | — |
| 17 | `neon_search_products` | Fuzzy keyword/filter search over data products with facets | — | `ProductSearchResult` | catalog (GraphQL `products(release)`; REST `GET /products?release=` fallback) | n | catalog | 25 (max 100) | page |
| 18 | `neon_search_prototype_datasets` | Search prototype datasets by text, theme, team, site, years, file type | — | `PrototypeSearchResult` | `GET /prototype/datasets` | n | prototype | 25 (max 200) | page |
| 19 | `neon_search_sites` | Fuzzy site lookup + domain/state/type/product/proximity filters, facets | — | `SiteSearchResult` | catalog (GraphQL `sites(release)`; REST `GET /sites?release=` fallback); `GET /locations/sites` for elevation | n | catalog | 50 (max 100) | page |
| 20 | `neon_search_taxonomy` | Paginated taxon lists by type code or rank (exact scientific name, genus fallback), Darwin-Core keys verbatim | one filter | `TaxonPage` | `GET /taxonomy?…` | n | taxonomy | 25 (max 500; 100 verbose) | page from NEON `next` |

`requiresToken` is true exactly for `{neon_list_files, neon_download_files, neon_get_sample}`.

#### Coverage of the old TypeScript server (RESEARCH §1.6)

`neon_list_products`+`neon_search_products` → `neon_search_products`; `neon_get_product` → `neon_get_product`; `neon_list_sites`+`neon_search_sites` → `neon_search_sites`; `neon_get_site`+`neon_get_site_products` → `neon_get_site` / `neon_get_availability(site=)`; `neon_get_location` → `neon_get_location`; `neon_list_site_locations` → `neon_find_locations(root="REALM", location_type="SITE")`; `neon_find_towers` → `neon_find_locations(site_codes=[…], location_type="TOWER")`; `neon_get_location_hierarchy`+`neon_search_locations` → `neon_find_locations` / `neon_get_location(include=["hierarchy"])`; `neon_query_data` → `neon_list_files`; `neon_get_download_url` → `neon_list_files(filename=)`; `neon_summarize_data_availability` → `neon_get_availability`. New: taxonomy, samples, releases, prototype, GraphQL, documents, downloads, citation.

#### Endpoint reachability matrix (every Swagger 0.11.0 path + the two undocumented ones)

| NEON path | Reached by |
|---|---|
| `GET /products?release=` | catalog REST fallback (`neon_search_products`, `neon_get_product` base) |
| `GET /products/{code}?release=` | `neon_get_product` (sections), `neon_get_availability` (fallback), `neon_get_citation`, `neon_get_document` (spec lookup), template `neon://products/{productCode}` |
| `GET /sites?release=` | catalog REST fallback (`neon_search_sites`) |
| `GET /sites/{code}?release=` | `neon_get_site`, `neon_get_availability` (fallback), template `neon://sites/{siteCode}` |
| `GET /locations/sites` | `neon_find_locations` (REALM+SITE fast path), `neon_search_sites(include_elevation)` |
| `GET /locations/{name}?history=&hierarchy=&locationType=` | `neon_get_location`, `neon_find_locations`, `neon_get_site(include=["location"])` |
| `GET /data/{p}/{s}/{ym}?package=&release=` | `neon_list_files` (single cell), `neon_download_files` |
| `GET /data/{p}/{s}/{ym}/{filename}` (302) | `neon_list_files(filename=)` → `Location`; `neon_download_files` |
| `GET /data/package/{p}/{s}/{ym}?package=` | `neon_list_files` (returns `packages[].url`), `neon_download_files(as_zip=true)` |
| `GET /data/query` | intentionally unused (identical to POST); documented |
| `POST /data/query` | `neon_list_files` (multi site-month), `neon_download_files` |
| `GET /releases`, `GET /releases/{id}` | `neon_list_releases`, `neon_get_release`, `neon_get_citation`, resource `neon://reference/releases` |
| `GET /releases/{tag}/products` (25.8 MB), `GET /releases/{tag}/sites` (22.2 MB) | **intentionally unused** (payload hazard); `neon_get_release(include=["sites"])` uses GraphQL `sites(release:)` |
| `GET /releases/{tag}/products/{code}`, `GET /releases/{tag}/sites/{code}` | `neon_get_release(product_code=)`, `neon_get_release(site_code=)` |
| `GET /releases/{tag}/data/**` | intentionally unused (`?release=` on `/data/**` is equivalent); documented |
| `GET /samples/supportedClasses`, `GET /samples/classes?sampleTag=` | `neon_list_sample_classes`, `neon_get_sample` (disambiguation) |
| `GET /samples/view`, `GET /samples/download?degree=` | `neon_get_sample` |
| `GET /taxonomy?…` (all params; `stream` never sent) | `neon_search_taxonomy`, `neon_ping(check_api)` |
| `GET /prototype/datasets`, `GET /prototype/datasets/{uuid}` | `neon_search_prototype_datasets`, `neon_get_prototype_dataset`, `neon_get_citation(prototype_uuid=)` |
| `GET /prototype/data/{uuid}`, `GET /prototype/data/{uuid}/{filename}` | `neon_get_prototype_dataset(include=["files"])`, `neon_download_files(prototype_uuid=)` |
| `GET /documents/{specNumber}` (undocumented; HEAD verified) | `neon_get_document`, `neon_download_files(spec_number=)` |
| `POST /graphql` | `neon_graphql`; internally catalog, availability, `findLocations`, `sites(release:)` |

A conformance test turns this matrix into a coverage assertion: the union of `io.neon-mcp/endpoints` over registered tools equals the set of "reached" paths above (the "intentionally unused" rows are listed in a `DOCUMENTED_UNUSED` constant in the test).

### 1.3 Per-tool specifications (exact pydantic fields; `?` = optional; defaults shown)

#### `neon_ping` — core
Input `PingIn`: `check_api: bool = False`.
Behaviour: no network unless `check_api`; then one `GET /taxonomy?taxonTypeCode=TICK&limit=1` (never cached) to read `X-RateLimit-*` and confirm reachability. Never returns the token, its length, hash or prefix.
Output `PingResult(ToolResultBase)`: `pong: "ok"`, `version`, `protocolVersion` (= `t.LATEST_PROTOCOL_VERSION`), `transport: "stdio"|"http"`, `tokenConfigured: bool`, `tokenSource: "config"|"request"|"none"`, `downloadsEnabled: bool`, `downloadDir: str|null` (stdio only), `apiBaseUrl`, `graphqlUrl`, `catalog: {products: "warm"|"cold"|"warming", sites: …, source: "graphql"|"rest"|null, ageSeconds: int|null, graphqlFallbacks: int, breakerOpen: bool}`, `cache: {entries, hits, misses}`, `rateLimit: {limit, remaining, resetSeconds, identity}|null`, `api: {reachable: bool, latencyMs: int}|null`.

#### `neon_search_products` — catalog
Input `SearchProductsIn`: `query: str|None` (AND of whitespace tokens over code/name/description/keywords/themes; a bare code short-circuits), `theme: str|None` (case-insensitive prefix on the 5 NEON themes), `science_team: Literal["TIS","TOS","AOP","AOS","AIS"]|None`, `status: Literal["ACTIVE","FUTURE","RETIRED","ALL"] = "ACTIVE"`, `level: int|None (1..4)`, `has_expanded: bool|None`, `site: str|None` (fuzzy; ≥ 1 available month there), `domain_code: DomainCode|None`, `release: ReleaseTag|None` (catalog loaded with `products(release:)`), `available_from: Month|None`, `available_to: Month|None` (overall month range overlaps), `sort: Literal["relevance","productCode","productName"] = "relevance"`, `limit: int = 25 (1..100)`, `offset: int = 0`.
Ranking (`catalog.ProductIndex.search`): exact code 100; name phrase 40; per name token 10; keyword exact 8; keyword fuzzy (difflib ≥ 0.85) 6; theme token 5; description token 2; ties by code. `didYouMean` = top-3 keywords/name tokens by fuzzy distance when 0 hits.
Output `ProductSearchResult`: `items: [ProductSummary]`, `page`, `facets: {themes, scienceTeams, levels, productStatus}` (over the filtered set before paging), `didYouMean: [str]|null`, `indexSource: "graphql"|"rest"`, `indexAgeSeconds: int` + envelope.

#### `neon_get_product` — catalog
Input `GetProductIn`: `product: str` (fuzzy), `release: ReleaseTag|None`, `include: list[Literal["abstract","design","study","sensor","remarks","packages","specs","releases","change_logs","availability","biorepository","all"]] = []`, `change_logs_limit: int = 25 (≤200)`, `change_logs_offset: int = 0`, `availability_limit: int = 100 (≤300)`, `availability_offset: int = 0`, `text_budget: int = 4000 (≤20000)`.
Source: `include == []` and catalog warm → served from the catalog (`source.via="local"`; `changeLogCount: null`). Any section (or `release`) → `GET /products/{code}?release=` (`detail` cache). `availability` → the product-mode rows of `neon_get_availability` inline.
Output `ProductDetail(ToolResultBase)` — §4.2.

#### `neon_get_availability` — catalog (token-free)
Input `GetAvailabilityIn`: `product: str|None` (fuzzy), `site: str|None` (fuzzy) — ≥ 1 required; `site_codes: list[str]|None` (row filter, product mode, fuzzy, ≤ 81), `domain_code: DomainCode|None`, `product_codes: list[ProductCode]|None` (row filter, site mode), `release: ReleaseTag|None`, `provisional: Literal["include","exclude","only"] = "include"` (`only` ⇒ `release` must be absent), `start_month: Month|None`, `end_month: Month|None`, `format: Literal["ranges","months","counts"] = "ranges"` (`months` allowed only when rows×months ≤ 2000, else `invalid_argument` suggesting `ranges`), `limit: int = 100 (≤500)`, `offset: int = 0`.
Modes: product → one row per site; site → one row per product; both → `mode="cell"` (one row, default `format="months"`).
Source: GraphQL `filterProducts(filter:{productCodes:[code], siteCodes?, startMonth?, endMonth?, release?})` / `filterSites(filter:{siteCodes:[code], productCodes?, …})` — `availableReleases[].availableMonths` clipped locally to the window (`notes` records it); fallback REST detail + local filtering. Both paths feed one projection; a parity test asserts byte-identical rows.
Output `AvailabilityMatrix` — §4.5.

#### `neon_search_sites` — catalog
Input `SearchSitesIn`: `query: str|None` (code, name, description, state/domain names), `domain_code`, `state_code: str|None` (2 letters), `site_type: Literal["CORE","GRADIENT"]|None`, `product: str|None` (fuzzy; sites with ≥ 1 month of it), `release: ReleaseTag|None`, `latitude: float|None (-90..90)`, `longitude: float|None`, `radius_km: float = 100 (≤5000)` (all three → nearest first, `distanceKm` added), `include_elevation: bool = False` (joins `/locations/sites`, 2.7 MB cached 6 h), `limit: int = 50 (≤100)`, `offset: int = 0`.
Ranking: exact code 100; name phrase 40; token 10; state/domain 6; fuzzy name ratio ≥ 0.8 → 20.
Output `SiteSearchResult`: `items: [SiteSummary]`, `page`, `facets: {domains, states, siteTypes}`, `didYouMean`, `indexSource`, `indexAgeSeconds` + envelope.

#### `neon_get_site` — catalog
Input `GetSiteIn`: `site: str` (fuzzy), `release: ReleaseTag|None`, `include: list[Literal["products","releases","description","location","all"]] = ["products"]`, `products_query: str|None`, `products_limit: int = 100 (≤300)`, `products_offset: int = 0`.
Source: `GET /sites/{code}?release=` (317 KB, `detail` cache); `location` → `GET /locations/{siteCode}`.
Output `SiteDetail` — §4.4.

#### `neon_find_locations` — locations
Input `FindLocationsIn`: exactly one of `root: LocationName` (`REALM`, `D01`, `HARV`, `TOWER100450`, …) or `site_codes: list[str]` (1..20, fuzzy); `location_type: str|None` (upper-cased where NEON's vocabulary is upper-case; passed verbatim otherwise, e.g. `OS Plot - mam`); `query: str|None` (substring on name/description); `latitude`/`longitude`/`radius_km` (need coordinates); `include_coordinates: bool = True`; `max_depth: int = 6 (1..12)`; `limit: int = 50 (≤200)`; `offset: int = 0`.
Guards (D26): `root` is `REALM` or a domain and `location_type` is `None` → `invalid_argument` ("pass location_type; see neon://reference/vocabularies"). Fast paths: `REALM`+`SITE` → `GET /locations/sites` (88 items, `isFieldSite` false for `HQTW, MD00–MD04, SITE03C`); `REALM`+`DOMAIN` → `GET /locations/REALM?hierarchy=true&locationType=DOMAIN` (20). Otherwise per root `GET /locations/{root}?hierarchy=true[&locationType=]` (cached 6 h, concurrency 4), depth-first flatten to `(name, type, description, parent, depth)`, filter, sort by name, page. `typesAvailable` computed only when the fetch was unfiltered. `include_coordinates` → one GraphQL `findLocations(query:{locationNames:[…page…]})` per page (≤ 50 names), REST `GET /locations/{name}` fan-out (concurrency 4) as fallback; per-item failures → `detailError: {code, message}` on the item.
Output `LocationList`: `roots: [{locationName, locationType}]`, `locationType`, `typesAvailable: {TYPE: count}|null`, `hierarchyNodesScanned: int`, `items: [LocationSummary]`, `page` + envelope. `nextSteps` explains batching when 20 site codes are supplied.

#### `neon_get_location` — locations
Input `GetLocationIn`: `name: LocationName`, `include: list[Literal["properties","hierarchy","history","children","polygon","all"]] = ["properties"]`, `location_type: str|None` (prunes the child hierarchy upstream), `children_limit: int = 50 (≤500)`, `children_offset: int = 0`, `hierarchy_max_depth: int = 3 (1..12)`.
Guard: `hierarchy`/`children` on `REALM` or a domain without `location_type` → `invalid_argument`; on a SITE root allowed with `notes` ("pass location_type to prune") and `hierarchyNodesScanned`.
Source: `GET /locations/{name}?history=&hierarchy=&locationType=` (only params actually set are sent; cached 6 h).
Output `LocationDetail` — §4.5.

#### `neon_list_files` — data (token)
Input `ListFilesIn`: `product: str` (fuzzy), `site_codes: list[str]` (1..`limits.max_sites_per_call`=30, fuzzy), `start_month: Month`, `end_month: Month|None` (default = start), `package: PackageType = "basic"`, `release: ReleaseTag|None`, `include_provisional: bool = True`, `detail: Literal["files","site_months","summary"] = "files"`, `include_urls: bool = True`, `kind: FileKind|None`, `table: str|None` (e.g. `2DWSD_30min`, `brd_countdata`), `hor: str|None`, `ver: str|None`, `tmi: str|None`, `name_contains: str|None`, `filename: str|None` (exact NEON file name; single-cell only → `GET /data/{p}/{s}/{m}/{filename}` with `follow_redirects=False`, 302 `Location` is the signed URL; 200 falls back to the listing), `limit: int = 50 (≤200)`, `offset: int = 0`.
Endpoint choice: one site and `start_month == end_month` → `GET /data/{p}/{s}/{m}?package=&release=` (also yields `packages[]` ZIP URLs and `externalData`); otherwise `POST /data/query` body exactly `{productCode, siteCodes, startDateMonth, endDateMonth[, release], package, includeProvisional}`. Guard (D27): `len(sites) × months > limits.max_site_months_per_query` → `query_too_large`. Both responses normalise to one flattened list sorted `(release desc, siteCode, month, name)`; `parse_neon_filename` fills `kind/table/hor/ver/tmi`; `urlExpiresAt` from `X-Goog-Date`+`X-Goog-Expires` of the first URL.
Output `FileListing` — §4.6. Budget rule: URLs are nulled from the tail (`urlsElided: true`) before records are dropped.

#### `neon_download_files` — data (stdio only; token for `/data/**`)
Input `DownloadFilesIn`: one selector group — (a) the `neon_list_files` selectors (`product`, `site_codes`, `start_month`, `end_month?`, `package`, `release?`, `include_provisional`, `kind?`, `table?`, `hor?`, `ver?`, `tmi?`, `name_contains?`) plus `as_zip: bool = False` (download `GET /data/package/{p}/{s}/{m}?package=` per site-month instead of files); (b) `prototype_uuid: Uuid` + `file_names: list[str]|None`; (c) `spec_number: SpecNumber`. Common: `dest_subdir: str|None` (relative, sanitised: no `..`, not absolute, `/` only), `if_exists: Literal["skip","error"] = "skip"`, `max_bytes: int|None` (≤ `downloads.max_bytes_per_call`).
Guards: transport must be stdio (the tool is absent from the HTTP list; a direct `call()` still returns `not_available_in_http_mode` with the signed URLs in `details`); `downloads.enabled`; redirect/GCS hosts must match `downloads.allowed_hosts` (suffix match); ≤ `max_files_per_call` (50) and ≤ `max_bytes_per_call` (2 GiB) computed from the listing **before** any transfer (`download_limit_exceeded` with totals and how to narrow); per-file `max_file_bytes` (1 GiB); `.part` + `os.replace`; md5 verified when NEON supplies one (`checksum_mismatch` → partial removed); existing file with matching size (+ md5 when known) → `skipped`; `if_exists="error"` → `download_denied` listing the existing paths. Layout: `{directory}/{productCode}/{siteCode}/{month}/{name}`, `{directory}/prototype/{uuid}/{name}`, `{directory}/documents/{specNumber}.pdf`; basenames must match `^[A-Za-z0-9._-]+$`; real-path (symlink-safe) confinement under `directory.resolve()`.
Output `DownloadReport(ToolResultBase)`: `downloadDir`, `requested: int`, `files: [{path, name, size, md5Verified: bool|null, status: "downloaded"|"skipped"|"failed", error: str|null}]`, `totals: {files, bytes, seconds}`; `nextSteps` includes a `pandas.read_csv` hint.
Annotations: `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true`. `_meta`: `requiresToken: true`, `stdioOnly: true`.

#### `neon_list_releases` — releases
Input `ListReleasesIn`: `include_artifact_urls: bool = False`.
Output `ReleaseList`: `items: [ReleaseSummary]` (newest first), `latestRelease: str`, `page` + envelope. Source `GET /releases` (cached 6 h). Six releases today.

#### `neon_get_release` — releases
Input `GetReleaseIn`: `release: ReleaseId` (tag, UUID, or `latest`), `include: list[Literal["products","sites","artifacts","all"]] = ["products"]`, `product_query: str|None`, `products_limit: int = 50 (≤500)`, `products_offset: int = 0`, `product_code: ProductCode|None` (→ `GET /releases/{tag}/products/{code}`: the product as published in that release, projected as `ProductDetail` base + availability summary), `site_code: SiteCode|None` (→ `GET /releases/{tag}/sites/{code}` → `SiteDetail`), `include_artifact_urls: bool = False`.
`sites` → GraphQL `sites(release:) { siteCode siteName domainCode stateCode }` (~200 KB, catalog cache) — never the 22.2 MB REST list. UUIDs resolve to tags via the cached releases list. Unknown → 400 "Release not found" → `not_found` with `details.validReleases`.
Output `ReleaseDetail` — §4.7.

#### `neon_get_citation` — releases
Input `GetCitationIn`: exactly one of `product: str` (fuzzy) / `prototype_uuid: Uuid`; `release: ReleaseTag | Literal["latest"] = "latest"` (newest release with a `productDoi`); `provisional: bool = False` (mutually exclusive with an explicit tag); `format: Literal["text","bibtex","all"] = "all"`; `accessed_on: date|None` (default today UTC); `site_codes: list[str]|None` (echoed as "Data for sites …" in `notes`).
Source: `GET /products/{code}` → `releases[]` (`productDoi.url`), cross-checked against `GET /releases/{tag}` `dataProducts[].productDoi` (mismatch → `notes`). Templates come from `resources.citation_templates()` (parsed from `resources_static/citing_neon_data.md`, D23). BibTeX rendered locally: `@misc{neon_{code_slug}_{release}, author={{NEON (National Ecological Observatory Network)}}, title={{name} ({code}), {release}}, year={yyyy}, doi={10.48443/…}, url={…}, note={Dataset accessed from https://data.neonscience.org on …}}`. No DOI for the tag → `not_found` with `details.availableReleases`.
Output `Citation(ToolResultBase)`: `productCode|null`, `prototypeUuid|null`, `productName|projectTitle`, `release|null`, `provisional: bool`, `doi: str|null` (bare), `doiUrl: str|null`, `accessedOn`, `citationText: str|null`, `bibtex: str|null`, `dataPolicyUrl: "https://www.neonscience.org/data-samples/data-policies-citation"`.

#### `neon_search_taxonomy` — taxonomy
Input `SearchTaxonomyIn`: `taxon_type_code: TaxonTypeCode|None`; rank filters `kingdom, phylum, division, class_ (alias class), order, family, genus, scientific_name (aliases scientificname, scientificName; exact match upstream)`; `verbose: bool = False`; `fuzzy_genus_fallback: bool = True`; `limit: int = 25 (1..500; capped at 100 when verbose)`; `offset: int = 0`.
Validation before the request: `taxon_type_code` with any rank filter → `invalid_argument` (NEON's exact message is quoted); at least one filter required. Fuzzy fallback: `scientific_name` returned 0 rows and contains a space → retry with `genus=<first token>`, keep rows whose `dwc:scientificName` starts with the input (case-insensitive), `fuzzyFallbackUsed: true`.
Wire: `GET /taxonomy?…&offset=&limit=&verbose=`; `stream` never sent. Response is unenveloped `{count,total,prev,next,data[]}` → `page` (`returned=count`, `truncated = next is not null`, `nextOffset` parsed from `next`). Cached 24 h per exact query string.
Output `TaxonPage`: `items: [dict]` (NEON keys verbatim including `dwc:`/`gbif:` prefixes; verbose drops null-valued ranks), `page`, `filters` (echo), `fuzzyFallbackUsed` + envelope.

#### `neon_list_sample_classes` — samples
Input `ListSampleClassesIn`: `sample_tag: str|None`, `query: str|None` (substring on key/description), `limit: int = 50 (≤500)`, `offset: int = 0`.
`sample_tag` → `GET /samples/classes?sampleTag=`; NEON 404 "No Sample Classes Found…" → `items: []` + `notes`, **not** an error. Otherwise `GET /samples/supportedClasses` (cached 24 h) filtered.
Output `SampleClassList`: `sampleTag: str|null`, `items: [{sampleClass, description: str|null}]`, `page`, `sourceEndpoint: "classes"|"supportedClasses"` + envelope.

#### `neon_get_sample` — samples (token; MRTR)
Input `GetSampleIn`: exactly one mode — `sample_tag: str` (+ `sample_class: str|None`), `sample_uuid: str`, `barcode: str`, `archive_guid: str`; `degree: int|None (1..5)` → `/samples/download?…&degree=` else `/samples/view`; `include_events: bool = True`; `events_limit: int = 50 (≤500)`; `fields: list[str]|None` (keep only these `smsKey`s); `limit: int = 20 (≤100)` views; `offset: int = 0`.
Disambiguation: `sample_tag` without `sample_class` → public `GET /samples/classes?sampleTag=`; one class → proceed; several → `InputRequired` (enum form, ≤ 8) when `ctx.elicitation_supported`, else `ambiguous_input` (`details.field="sample_class"`, `candidates`). `requestState` = `{v:1, tool, args (original), field:"sample_class", candidates, issuedAt}`; on resume the lookup re-runs and the answer must be in the fresh list; `issuedAt` > 1 h → `invalid_argument("continuation expired")`. Never cached (`samples_view` TTL 60 s keyed by token identity is the only cache).
Output `SampleViews` — §4.8.

#### `neon_search_prototype_datasets` — prototype
Input: `query: str|None` (title, abstract, description, keywords), `theme: str|None` (`dataThemes`; prefix, case-insensitive), `science_team: str|None` (abbr or substring), `site_code: SiteCode|None` (`locations[].siteCode`), `start_year: int|None`, `end_year: int|None` (overlap), `file_type: str|None` (`fileTypes[].name`), `is_published: bool|None = None`, `limit: int = 25 (≤200)`, `offset: int = 0`.
Source: `GET /prototype/datasets` (704 KB, cached 6 h, indexed in memory).
Output `PrototypeSearchResult`: `items: [PrototypeDatasetSummary]`, `page`, `facets: {dataThemes, scienceTeams, fileTypes}` + envelope.

#### `neon_get_prototype_dataset` — prototype
Input: `uuid: Uuid`, `include: list[Literal["files","descriptions","locations","citations","related","all"]] = ["files","locations"]`, `include_urls: bool = True`, `files_limit: int = 100 (≤500)`, `files_offset: int = 0`, `text_budget: int = 4000`.
Source: `GET /prototype/datasets/{uuid}` (cached 6 h) + `GET /prototype/data/{uuid}` (signed URLs, `data` TTL 10 min).
Output `PrototypeDatasetDetail` — §4.9.

#### `neon_get_document` — documents
Input `GetDocumentIn`: `spec_number: SpecNumber|None` or `url: str|None` (must start with `https://data.neonscience.org/api/v0/documents/`), `product: str|None` (fuzzy; look the spec up in that product's `specs[]`), `extract_text: bool = False`, `max_chars: int = 20000 (≤100000)`, `char_offset: int = 0`, `pages: str|None` (e.g. `1-5`).
Behaviour: `HEAD /documents/{spec}` (fallback `GET` with `Range: bytes=0-0`) → `contentType`, `size`, `filename` (from `content-disposition`); `referencedByProducts` from the catalog spec index. `extract_text` streams the body **in memory** up to `limits.max_document_bytes` (25 MiB; else `result_too_large`), extracts with `pypdf` (extra `neon-mcp[pdf]`; missing → `feature_unavailable` with `pip install "neon-mcp[pdf]"`), text cached 24 h (LRU 20 docs). Non-PDF specs (xlsx/csv/docx) → `text` only for `text/*`.
Output `Document(ToolResultBase)`: `specNumber`, `url`, `contentType`, `size: int|null`, `filename`, `specDescription|null`, `specType|null`, `referencedByProducts: [str]`, `text: str|null`, `textTruncated: bool`, `nextCharOffset: int|null`, `charsTotal: int|null`, `pageCount: int|null`.

#### `neon_graphql` — graphql
Input `GraphqlIn`: `query: str|None` (≤ `limits.graphql_max_query_chars` = 8000) xor `introspect_type: str|None` (runs `gql_queries.INTROSPECT_ONE`), `variables: dict|None`, `operation_name: str|None`, `max_bytes: int = 50000 (≤200000)`.
Guardrails (`neon/gql_guard.py::check_query`): operation `query` or shorthand only; every root field ∈ `ALLOWED_ROOTS` = `{products, product, demoProduct, filterProducts, sites, site, filterSites, location, locationHierarchy, findLocations, prototypeDatasets, prototypeDataset, __schema, __type}`; at most one `__type`/`__schema`; selection depth ≤ 8; balanced braces; 30 s timeout; never cached; no token (public endpoint). Response above `max_bytes` → drop the tail of the largest JSON array until it fits, `truncated: true`, `truncatedPaths: ["data.products[120:]"]`.
Output `GraphQLResult(ToolResultBase)`: `data`, `errors: [NEON error objects]|null` (errors **with** data → returned; errors with `data: null` → `graphql_error`; `BadFaithIntrospection` → `invalid_argument`), `bytesTotal`, `truncated`, `truncatedPaths`, `schemaHint: "neon://reference/graphql-schema"`.

---

## 2. Resources and prompts

All list/read results are `cacheScope: "public"` (nothing depends on the caller). A future token-dependent resource would have to use `private`; none exists in v1.

### 2.1 Resources (`resources/list` hint 1 h; `resources/read` 24 h static / 1 h derived — per-read `ReadResourceResult(ttl_ms, cache_scope)`)

| URI | mimeType | Kind | Content | Why |
|---|---|---|---|---|
| `neon://guide/agent-workflow` | text/markdown | static | The 5-step recipe (search → availability → files → download → cite) with the Appendix-B trace, fuzzy-input rules, `page.nextOffset`, `nextSteps`, error codes and remedies | Keeps tool descriptions short |
| `neon://guide/api-token` | text/markdown | static | Why (403 since 2026-06), myaccount, `NEON_MCP_NEON__API_TOKEN`/`NEON_TOKEN`, HTTP `X-API-Token`, which tools need it, rate tiers | Every `auth_required` links here |
| `neon://guide/citing-neon-data` | text/markdown | static | Data policy (CC-BY 4.0), released vs provisional wording, DOI rules, NSF acknowledgement; contains the fenced `citation-released`, `citation-provisional`, `citation-prototype`, `bibtex` templates `neon_get_citation` renders | Wording fixable without code |
| `neon://guide/product-code-anatomy` | text/markdown | static | `DP1.10003.001`, `productCodeLong`, packages, HOR/VER/TMI, file-name grammar, `FileKind`, release vs PROVISIONAL, 7-day URL expiry | Needed to filter `neon_list_files` |
| `neon://reference/vocabularies` | application/json | static | themes, science teams, site types, domains D01–D20 with names, taxon type codes, observed `locationType` vocabulary, release-tag pattern, package types, file kinds | Valid filter values without probing (and no extra hierarchy calls, D26) |
| `neon://reference/graphql-schema` | text/markdown | static (curated from `GRAPHQL_TYPES.md`) | Root fields, input types, object fields, one-`__type` rule, PROVISIONAL-is-not-a-release, fields GraphQL lacks | Makes `neon_graphql` usable |
| `neon://reference/sites` | application/json | derived (catalog) | 81 × `{siteCode, siteName, siteType, domainCode, stateCode, siteLatitude, siteLongitude}` (~10 KB) | Cheap whole-network context |
| `neon://reference/releases` | application/json | derived | `[{release, generationDate, productCount}]` + `latestRelease` | "What is the latest release?" without a tool call |

Each `Resource` carries `_meta={"io.neon-mcp/kind": "static"|"derived"}`. Static texts live in `src/neon_mcp/resources_static/` (package data), loaded once.

### 2.2 Resource templates (`resources/templates/list`, 1 h public)

| Template | Reads as |
|---|---|
| `neon://products/{productCode}` | `neon_get_product(product=…, include=[])` payload via `registry.invoke` (`application/json`) |
| `neon://sites/{siteCode}` | `neon_get_site(site=…, include=["products"])` payload |
| `neon://releases/{release}` | `neon_get_release(release=…, include=["products"])` payload |

Unknown/invalid → JSON-RPC `-32602`, `data={"code":"not_found","didYouMean":[…]}` (D32).

### 2.3 Prompts (`prompts/list` 24 h public)

| Prompt | Arguments | Message |
|---|---|---|
| `neon_find_data` | `question` (req), `region?`, `timeframe?`, `organism_or_variable?` | Run `neon_search_products` (theme hints from the question) → `neon_search_sites` for the region → `neon_get_availability` (state released vs provisional months) → if a token is configured `neon_list_files(detail="summary")` else explain the token step → end with a candidate table and `neon_get_citation`. Follow `page.nextOffset` before concluding. |
| `neon_cite_dataset` | `product` (req), `release?`, `site_codes?` | `neon_get_citation`; present text + BibTeX; add the provisional caveat when applicable. |
| `neon_plan_download` | `product`, `sites` (req, comma list), `start_month` (req), `end_month?`, `package?` | `neon_ping` (token?) → `neon_get_availability` → `neon_list_files(detail="summary", include_urls=false)` to size the pull → `neon_download_files` (stdio) or hand back URLs (http) → cite. |

One `user` `TextContent` message each, arguments validated with the shared types; no embedded resources.

---

## 3. NEON HTTP client (`neon_mcp/neon/`)

One `NeonClient` per process wrapping one `httpx.AsyncClient` (plain `httpx>=0.28`; the SDK's `httpx2` coexists). Created by `server.create_server()`, closed by `serve_stdio()`'s `finally` / `serve_http()`'s lifecycle. Modules: `neon/client.py`, `neon/auth.py`, `neon/ratelimit.py`, `neon/cache.py` (WP2); `neon/catalog.py`, `neon/months.py`, `neon/gql_queries.py`, `neon/gql_guard.py`, `neon/resolve.py` (WP3); `neon/filenames.py`, `neon/downloads.py` (WP6).

### 3.1 Construction

```python
class NeonClient:
    def __init__(self, config: NeonConfig, *, cache: TTLCache, limiter: RateLimiter,
                 send_token_on_public: bool,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None
```

* `httpx.AsyncClient(base_url=config.base_url, http2=False, follow_redirects=False, timeout=httpx.Timeout(connect=config.connect_timeout_s, read=config.read_timeout_s, write=10.0, pool=5.0), limits=httpx.Limits(max_connections=8, max_keepalive_connections=4), headers={"User-Agent": f"neon-mcp/{__version__} (+https://github.com/idss-mesa/neon-mcp)" + suffix, "Accept": "application/json", "Accept-Encoding": "gzip"})`.
* Per-family read timeouts: catalog fetches (`/products`, `/sites`, `/locations/sites`, `/prototype/datasets`, GraphQL catalog queries) `catalog_read_timeout_s` (180); downloads `download_read_timeout_s` (300); GraphQL 30 s; everything else the default.
* `follow_redirects=False`: the `/data/…/{filename}` 302 is handled explicitly (host allow-list on `Location`).
* `transport`, `clock`, `sleep` are the test seams.

### 3.2 Token model and injection (`neon/auth.py`)

```python
@dataclass(frozen=True)
class Token:
    value: str                                  # never printed: __repr__/__str__ → "Token(<redacted>, source=…)"
    source: Literal["config", "request"]
    def identity(self) -> str: ...              # "tok:" + sha256(value).hexdigest()[:12]

TOKEN_ENDPOINT_PREFIXES: tuple[str, ...] = ("/data/", "/samples/view", "/samples/download")
TOKEN_ENDPOINT_RE = re.compile(r"^/releases/[^/]+/data/")
def is_token_endpoint(path: str) -> bool
def resolve_token(config: Config, *, transport: Literal["stdio", "http"],
                  request_headers: Mapping[str, str] | None) -> Token | None
def require_token(ctx: ToolContext, *, endpoint: str) -> Token       # raises ToolError("auth_required")
def header_token_allowed(config: Config) -> bool                       # https public_base_url or allow_insecure_header_token
```

`resolve_token` precedence: **stdio** → `config.neon.api_token` (loader already applied the `NEON_TOKEN` fallback). **http** → inbound `X-API-Token` (`server.request_token_header`) when `server.accept_header_token` **and** `header_token_allowed(config)` (otherwise ignored with one warning per process); else the config token only when `server.share_config_token_over_http=true`; else `None`. Injection is header-only (`X-API-Token: <value>`), never the `apiToken=` query form, and only to `base_url.host`/`graphql_url.host` (`_headers_for(url, token)` — signed GCS URLs get no token). Public endpoints carry the token only when `send_token_on_public` (D9). Redaction: `logging.redact_secrets` drops keys matching `(?i)token|authorization|x-api-token` and masks any string equal to a bound token; tokens never appear in `ToolError.details`, `requestState`, `source`, `curlHint`, cache keys (only `identity()`), `/healthz`, `/readyz`.

### 3.3 Rate limiting and retries (`neon/ratelimit.py`)

```python
@dataclass
class RateLimitSnapshot: identity: str; limit: int | None; remaining: int | None; reset_at: float | None; bucket_tokens: float

class RateLimiter:
    def __init__(self, cfg: RateLimitConfig, *, max_concurrency: int,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None
    def slot(self, identity: str) -> AbstractAsyncContextManager[None]   # semaphore + token bucket + low-water pre-wait
    def observe(self, identity: str, headers: Mapping[str, str]) -> None   # X-RateLimit-Limit/Remaining/Reset → resync
    def penalize(self, identity: str, retry_after_s: float) -> None        # 429 → block this identity until now + retry_after
    def snapshot(self, identity: str) -> RateLimitSnapshot | None
```

* One bucket per identity: `"anon"` (180 burst / 1.8 rps) or `Token.identity()` (1800 / 7.2 rps) — 10 % under NEON's 200/2 and 2000/8; configurable. The identity of a request is the token actually attached to it (so a stdio user with `token_for_public_endpoints` runs on the token tier everywhere; an HTTP anonymous caller shares the process's anonymous per-IP budget — the honest model).
* `observe()` after every response; `remaining ≤ low_water (5)` → next `slot()` sleeps `min(reset_at − now, max_wait_s=10)`; still exhausted → `rate_limited` without calling upstream.
* 429: honour `RetryAfter` (NEON's spelling) then `Retry-After`; default 1 s; `penalize()`; retry ≤ `retries.max_attempts` (3); then `rate_limited` (`details.retryAfterSeconds`, `limit`, `identity`).
* 5xx / `httpx.TransportError` / `ReadTimeout`: exponential backoff `0.5·2^n` + jitter ≤ 250 ms, ≤ 3 attempts, on every NEON call we make (all are idempotent: GET, HEAD, `POST /data/query`, `POST /graphql`); downloads restart from scratch, never resume.
* Other 4xx: no retry.
* `asyncio.Semaphore(neon.max_concurrency=4)` around all upstream calls; fan-outs share it.
* `snapshot()` feeds `neon_ping`, `/readyz`, and the per-call `io.neon-mcp/upstream` `_meta`.

### 3.4 Public methods

```python
CacheHit = Literal["hit", "miss", "stale", "refreshed", "bypass"]

@dataclass
class Envelope(Generic[T]):
    data: T; status: int; headers: Mapping[str, str]; cache: CacheHit; elapsed_ms: float; endpoint: str

class NeonClient:
    async def get_json(self, path: str, params: Mapping[str, Any] | None = None, *, token: Token | None,
                       cache: CacheFamily | None = None, ttl_s: float | None = None, timeout_s: float | None = None,
                       stats: UpstreamStats | None = None) -> Envelope[Any]
    async def post_json(self, path: str, body: Mapping[str, Any], *, token: Token | None,
                        cache: CacheFamily | None = None, ttl_s: float | None = None, stats: UpstreamStats | None = None) -> Envelope[Any]
    async def graphql(self, query: GqlQuery | str, variables: Mapping[str, Any] | None = None, *, operation_name: str | None = None,
                      token: Token | None = None, cache: CacheFamily | None = None, ttl_s: float | None = None,
                      max_bytes: int | None = None, stats: UpstreamStats | None = None) -> Envelope[GraphQLPayload]
                      # GraphQLPayload = TypedDict(data: Any | None, errors: list[dict] | None)
    async def head(self, path_or_url: str, *, token: Token | None, stats: UpstreamStats | None = None) -> HeadInfo
                      # HeadInfo(url, status, content_type, content_length, filename)
    async def resolve_redirect(self, path: str, params: Mapping[str, Any] | None = None, *, token: Token | None,
                               stats: UpstreamStats | None = None) -> str | None          # 302 → Location, else None
    async def fetch_bytes(self, url: str, *, token: Token | None, max_bytes: int, stats: UpstreamStats | None = None) -> bytes
    async def stream_to_file(self, url: str, dest: Path, *, token: Token | None, max_bytes: int,
                             expected_md5: str | None, stats: UpstreamStats | None = None) -> StreamOutcome
                             # StreamOutcome(path, bytes, md5, md5_verified: bool | None, seconds); .part + os.replace; partial removed on failure
    def rate_limit_snapshot(self, identity: str) -> RateLimitSnapshot | None
    def cache_stats(self) -> CacheStats
    async def aclose(self) -> None
```

* Envelope unwrapping: NEON wraps most bodies as `{"data": …}`; `get_json` returns `body["data"]` when the body is exactly a `data`-only object, the whole body otherwise (`/taxonomy` is `{count,total,prev,next,data}`). Error bodies `{"error":{"status","detail"},"data": null | {"validReleases":[…]}}` and the 429 `{"message": …}` raise `NeonApiError(status, detail, path, retry_after_s, data, headers)`.
* Query params: `None` dropped; booleans `true/false`; lists repeated.
* Every call increments `stats.requests` (or `stats.cache_hits`), appends the endpoint template to `stats.endpoints`, and records the latest `X-RateLimit-*`.

### 3.5 Error mapping (`errors.py::map_api_error`)

| Upstream condition | `code` | Message / `details` |
|---|---|---|
| 403 on a token endpoint, no token sent | `auth_required` | "This NEON endpoint requires an API token. Create one at https://data.neonscience.org/myaccount and set NEON_MCP_NEON__API_TOKEN (or NEON_TOKEN); in HTTP mode send the X-API-Token header. Discovery tools work without a token." `details={guide:"neon://guide/api-token", endpoint, tokenSource:"none"}` |
| 403 with a token sent | `forbidden` | "NEON rejected the API token (expired or revoked?)"; `details={endpoint}` — never the token |
| 400 whose `detail` matches `/not found/i`; any 404 | `not_found` | `details={entity, identifier, validReleases?}` + tool-specific `didYouMean` |
| other 400 | `invalid_argument` | NEON `detail` after `redact()` |
| 429 after retries | `rate_limited` | `details={retryAfterSeconds, limit, remaining, identity}` |
| 5xx after retries | `upstream_error` | `details={status, endpoint}` (body ≤ 200 chars, redacted) |
| timeout / connect failure after retries | `upstream_unavailable` | `details={reason, endpoint}` |
| GraphQL `errors[]` with `data == null` | `graphql_error` (or `not_found` when a message matches "not found") | `details={errors:[NEON error objects]}` |
| GraphQL `BadFaithIntrospection` | `invalid_argument` | "NEON allows a single `__type`/`__schema` per query" |
| non-JSON body | `upstream_error` | `details={status, contentType}` |
| pydantic validation | `invalid_argument` | first error location + message; `details={tool, errors}` |
| local policy | `ambiguous_input`, `not_available_in_http_mode`, `download_limit_exceeded`, `download_denied`, `checksum_mismatch`, `query_too_large`, `result_too_large`, `feature_unavailable`, `catalog_unavailable`, `unknown_tool`, `internal_error` (with `correlationId` = request id; tracebacks never reach the wire) | as named |

Every `ToolError` → `CallToolResult(is_error=True, content=[TextContent(json)], structured_content={"error": {code, message, details, hint}})`. Only protocol failures (header mismatch, unsupported version, malformed JSON-RPC) surface as JSON-RPC errors — the SDK produces those.

### 3.6 Caching (`neon/cache.py`)

```python
CacheFamily = Literal["catalog", "detail", "locations", "releases", "taxonomy", "samples_classes", "samples_view", "data", "prototype", "documents"]

class TTLCache:
    def __init__(self, cfg: CacheConfig, *, clock: Callable[[], float] = time.monotonic) -> None
    async def get_or_fetch(self, family: CacheFamily, key: str, fetch: Callable[[], Awaitable[T]], *,
                           ttl_s: float | None = None, stale_if_error: bool = True) -> tuple[T, CacheHit]   # single-flight per key
    def peek(self, family: CacheFamily, key: str) -> Any | None
    def put(self, family: CacheFamily, key: str, value: Any, *, ttl_s: float) -> None
    def invalidate(self, family: CacheFamily | None = None, key: str | None = None) -> int
    def stats(self) -> CacheStats                       # entries, hits, misses, stale_served, families: {name: entries}
    def start_background(self, tg: anyio.abc.TaskGroup) -> None   # enables refresh-ahead tasks (http mode)
def cache_key(method: str, path: str, params: Mapping[str, Any] | None = None, *, body: Any = None, token_scope: str | None = None) -> str
```

* In-memory only. LRU per family with `cache.max_entries` (1024) overall and `cache.max_index_entries` (4) for catalog index objects.
* **Single-flight**: per-key `asyncio.Lock` so concurrent misses perform one fetch (critical for the multi-MB catalog builds).
* **Refresh-ahead / stale-if-error** (B): an access within the last `refresh_ahead` (10 %) of the TTL returns the current value and schedules a background refresh (http mode only, task group owned by `serve_http`); expired entries are served for up to `stale_if_error_s` (24 h) when the refresh fails, reported as `cache="stale"` and surfaced as `indexAgeSeconds`/`notes`.
* Keys: public endpoints `f"{method} {path}?{urlencode(sorted(params))}"` (never token-scoped, D9); token endpoints add `|{token.identity()}`; POST bodies canonical-JSON-hashed.

| Family | Contents | TTL (`cache.ttl_s.*`) | Cap |
|---|---|---|---|
| `catalog` | `ProductIndex`, `SiteIndex` (built objects; raw dropped), `/locations/sites`, `/releases`, `/prototype/datasets`, `/samples/supportedClasses`, GraphQL `sites(release:)` | 3600 (`catalog`) | 4 index entries; 32 others |
| `detail` | `/products/{code}`, `/sites/{code}`, `/releases/{id}`, `/releases/{tag}/products|sites/{code}`, `/prototype/datasets/{uuid}`, GraphQL `filterProducts`/`filterSites`/`findLocations` | 900 | 64 |
| `locations` | `/locations/{name}` variants | 21600 | 256 |
| `releases` | (`/releases*` share `detail`/`catalog`; family kept for stats) | 21600 | 32 |
| `taxonomy` | `/taxonomy` pages by exact query | 86400 | 256 |
| `samples_classes` | `supportedClasses`, `classes?sampleTag` | 86400 | 128 |
| `samples_view` | `view`/`download` (token-scoped) | 60 | 64 |
| `data` | `/data/**` listings, `/data/query`, `/prototype/data/{uuid}` (token-scoped where applicable; URLs live 7 d) | 600 | 128 |
| `prototype` | (detail shares `detail`; family for stats) | 21600 | 64 |
| `documents` | HEAD metadata, extracted text (≤ 20 docs) | 86400 | 32 |

Never cached: `neon_graphql` user queries, the ping probe, downloads.

### 3.7 The catalogs: fetched once, projected immediately, indexed (`neon/catalog.py`, WP3)

The 30.3 MB `/products` and 26.8 MB `/sites` bodies are never requested on the default path.

```graphql
# gql_queries.PRODUCTS_CATALOG   (expected_fields: productCode productName productStatus productScienceTeam siteCodes)
query NeonMcpProductsCatalog($release: String) {
  products(release: $release) {
    productCode productName productDescription productStatus productScienceTeam productPublicationFormatType
    productHasExpanded themes keywords
    releases { release generationDate url productDoi { url generationDate } }
    siteCodes { siteCode availableMonths }
    specs { specNumber specDescription specType specSize }
  }
}
# gql_queries.SITES_CATALOG      (expected_fields: siteCode siteName siteType domainCode stateCode siteLatitude siteLongitude dataProducts)
query NeonMcpSitesCatalog($release: String) {
  sites(release: $release) {
    siteCode siteName siteDescription siteType siteLatitude siteLongitude stateCode stateName domainCode domainName deimsId
    releases { release } dataProducts { dataProductCode dataProductTitle }
  }
}
# gql_queries.SITES_FOR_RELEASE  (neon_get_release include=sites): sites(release: $release) { siteCode siteName domainCode stateCode }
# gql_queries.PRODUCT_AVAILABILITY: filterProducts(filter: $f) { productCode productName siteCodes { siteCode availableMonths availableReleases { release availableMonths } } }
# gql_queries.SITE_AVAILABILITY:    filterSites(filter: $f) { siteCode siteName dataProducts { dataProductCode dataProductTitle availableMonths availableReleases { release availableMonths } } }
# gql_queries.LOCATIONS_BATCH:      findLocations(query: $q) { locationName locationType locationDescription siteCode domainCode locationDecimalLatitude locationDecimalLongitude locationElevation locationUtmEasting locationUtmNorthing locationUtmZone locationUtmHemisphere locationParent activePeriods { activatedDate deactivatedDate } }
# gql_queries.INTROSPECT_ONE:       __type(name: $n) { name kind description fields { name type { name kind ofType { name kind ofType { name kind } } } } inputFields { name type { name kind ofType { name kind ofType { name kind } } } } }
```

Every `GqlQuery` pairs its document with `expected_fields`; a missing field on the first record is a drift signal that triggers the REST fallback and a warning log with the diff. Derived fields (GraphQL lacks them; string forms verified in the api-fidelity pass): `productScienceTeamAbbr` = text in the trailing parentheses of `productScienceTeam`; `productCategory = f"Level {productCode[2]} Data Product"`; `productCodeLong = f"NEON.DOM.SITE.{productCode}"`; `productCodePresentation = "NEON." + productCode.rsplit(".", 1)[0]`; listed in `source.derived`. Size: the api-fidelity probe measured ≈ 3.2 MB for this selection (re-measured in WP9); REST fallback (`GET /products?release=`) is `json.loads`-ed once, projected, dropped.

```python
@dataclass(frozen=True)
class ProductRecord:
    product_code: str; product_code_long: str; product_code_presentation: str; product_name: str; product_description: str
    product_status: str; product_science_team: str; product_science_team_abbr: str | None; product_category: str; level: int
    product_publication_format_type: str | None; product_has_expanded: bool
    themes: tuple[str, ...]; keywords: tuple[str, ...]
    releases: tuple[ReleaseRef, ...]                 # ReleaseRef(release, generation_date, url, doi_url)
    specs: tuple[SpecRef, ...]                       # SpecRef(spec_number, description, spec_type, spec_size)
    months_by_site: Mapping[str, MonthRanges]
    def site_codes(self) -> tuple[str, ...]; def all_months(self) -> MonthRanges; def latest_release(self) -> str | None

@dataclass(frozen=True)
class SiteRecord:
    site_code: str; site_name: str; site_description: str; site_type: str; latitude: float; longitude: float
    state_code: str; state_name: str; domain_code: str; domain_name: str; deims_id: str | None
    releases: tuple[str, ...]; product_codes: tuple[str, ...]; product_titles: Mapping[str, str]

class ProductIndex:
    source: Literal["graphql", "rest"]; built_at: float; release: str | None; records: tuple[ProductRecord, ...]
    @classmethod
    def from_graphql(cls, payload: Mapping[str, Any], *, release: str | None) -> "ProductIndex"
    @classmethod
    def from_rest(cls, payload: Mapping[str, Any], *, release: str | None) -> "ProductIndex"
    def by_code(self, code: str) -> ProductRecord | None
    def normalize_code(self, text: str) -> str | None                 # "DP1.10003", "NEON.DP1.10003.001" → "DP1.10003.001"
    def search(self, q: ProductQuery) -> SearchResult[ProductRecord]  # ProductQuery(query, theme, team, status, level, has_expanded, site_code, domain_sites, release, available_from, available_to, sort, limit, offset)
    def facets(self, records: Sequence[ProductRecord]) -> dict[str, dict[str, int]]
    def fuzzy_candidates(self, text: str, n: int = 8) -> list[Candidate]   # Candidate(code, label, score)
    def spec_lookup(self, spec_number: str) -> tuple[SpecRef | None, list[str]]   # (spec, referencing product codes)

class SiteIndex:
    source; built_at; release; records
    @classmethod from_graphql(...); @classmethod from_rest(...)
    def by_code(self, code: str) -> SiteRecord | None
    def search(self, q: SiteQuery) -> SearchResult[SiteRecord]        # SiteQuery(query, domain_code, state_code, site_type, product_code, lat, lon, radius_km, limit, offset)
    def nearest(self, lat: float, lon: float, radius_km: float) -> list[tuple[SiteRecord, float]]
    def facets(self, records) -> dict[str, dict[str, int]]
    def fuzzy_candidates(self, text: str, n: int = 8) -> list[Candidate]
    def domains(self) -> dict[str, str]; def codes(self) -> frozenset[str]

@dataclass
class SearchResult(Generic[T]): total: int; items: list[tuple[T, float, list[str]]]   # (record, score, matched_on)

class Catalog:
    def __init__(self, client: NeonClient, cache: TTLCache, config: Config) -> None
    async def products(self, *, release: str | None = None, token: Token | None = None, stats: UpstreamStats | None = None) -> ProductIndex
    async def sites(self, *, release: str | None = None, token: Token | None = None, stats=None) -> SiteIndex
    async def sites_for_release(self, release: str, *, token=None, stats=None) -> list[dict[str, Any]]      # GraphQL SITES_FOR_RELEASE
    async def site_locations(self, *, token=None, stats=None) -> list[dict[str, Any]]                        # GET /locations/sites
    async def releases(self, *, token=None, stats=None) -> list[dict[str, Any]]                              # GET /releases
    async def prototype_datasets(self, *, token=None, stats=None) -> list[dict[str, Any]]
    async def sample_classes(self, *, token=None, stats=None) -> list[dict[str, Any]]
    async def product_detail(self, code: str, *, release: str | None, token=None, stats=None) -> dict[str, Any]
    async def site_detail(self, code: str, *, release: str | None, token=None, stats=None) -> dict[str, Any]
    async def release_detail(self, identifier: str, *, token=None, stats=None) -> dict[str, Any]
    async def product_availability(self, codes: Sequence[str], *, site_codes: Sequence[str] | None, start: str | None, end: str | None,
                                   release: str | None, token=None, stats=None) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]
    async def site_availability(self, codes: Sequence[str], *, product_codes: Sequence[str] | None, start, end, release, token=None, stats=None) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]
    async def locations_batch(self, names: Sequence[str], *, token=None, stats=None) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]
    async def prewarm(self) -> None                       # products + sites; sets warmth "warming" → "warm" | "degraded"
    def warmth(self) -> CatalogStats                      # CatalogStats(products, sites: "warm"|"cold"|"warming", source, age_s, graphql_fallbacks, breaker_open)
```

GraphQL circuit breaker (B): after `neon.graphql_breaker_failures` (2) consecutive GraphQL failures, catalog/availability/location-batch calls go straight to REST for `neon.graphql_breaker_cooldown_s` (900); every fallback is logged (`neon.graphql_fallback`), counted (`neon_ping.catalog.graphqlFallbacks`) and visible per result as `indexSource`/`source.via`. Both builders feed the same normaliser; a parity test asserts `ProductIndex.from_graphql(...)` and `ProductIndex.from_rest(...)` produce identical `records` for the shared fixtures.

### 3.8 GraphQL vs REST decision rules

| Need | Primary | Fallback | Trigger |
|---|---|---|---|
| Product/site list, search, facets, `neon_get_product(include=[])` base | GraphQL `products(release)` / `sites(release)` | `GET /products?release=` / `GET /sites?release=` | non-200, `errors` without `data`, timeout, missing expected field, breaker open |
| Product/site detail sections | REST `GET /products/{code}` / `GET /sites/{code}` | — (only REST has `changeLogs`, `specs[].specId/specUrl`, `productSensor`, `productRemarks`, `biorepositoryCollections`, `availableDataUrls`) | — |
| Availability (product × sites × window × release) | GraphQL `filterProducts` / `filterSites` | REST detail + local clip | as row 1 |
| Batch location coordinates (≤ 50 names) | GraphQL `findLocations` | REST `GET /locations/{name}` × N (concurrency 4) | as row 1; per-item `detailError` |
| Release site list | GraphQL `sites(release:)` codes-only | `/releases/{tag}/sites` is **never** used (22.2 MB); return `notes` "site list unavailable" | — |
| Hierarchy / history / `locationType` pruning | REST only | — | GraphQL `locationHierarchy` unverified (R14) |
| Releases, taxonomy, samples, prototype files, data, documents | REST only | — | not in GraphQL |

### 3.9 `release` and provisional semantics

`?release=RELEASE-YYYY` (and GraphQL `release:`) restricts availability/files to that release; `availableReleases[]` then holds only that tag. Invalid tag → 400 "Release not found…" + `data.validReleases` → `not_found(entity="release", validReleases=[…])`. `PROVISIONAL` exists only inside `availableReleases[].release` and as `includeProvisional` on `/data/query`; the `ReleaseTag` type rejects it locally (D6). `/releases/{id}` accepts tag or UUID; the `/releases/{tag}/…/{code}` endpoints accept tags only (UUIDs resolved through the cached list). Per-release DOIs: `product.releases[].productDoi.url` (REST/GraphQL) and `release.dataProducts[].productDoi` (bare URL string) — `neon_get_citation` cross-checks.

### 3.10 Observability (`logging.py`)

structlog events, never containing token values (`redact_secrets` processor): `neon.http {method, path, query_keys, status, ms, attempt, cache, identity, rl_remaining, rl_limit, request_id}`, `neon.graphql_fallback {query, reason, missing_fields}`, `tool.call {tool, ms, ok, code, result_bytes, truncated, upstream_requests, cache_hits, request_id}`, `cache.refresh`, `cache.stale_served`. httpx loggers forced to WARNING (they print full URLs). stdio → console renderer on stderr; http → JSON with `request_id` bound by the middleware. Nothing but MCP framing ever goes to stdout (asserted by a test).

---

## 4. Projection / formatting layer (`neon_mcp/projections/`, models in `neon_mcp/models/`)

Rules: (1) output keys are NEON keys wherever a NEON field exists; neon-mcp's own fields are camelCase (D1); (2) month lists are compressed to inclusive ISO-8601 interval strings `"YYYY-MM/YYYY-MM"` (D24) unless `format="months"`; (3) long text is clipped (300 chars in summaries, `text_budget` = 4000 in details) with a trailing `…` and `<field>Truncated: true`; (4) every list carries `page`; (5) NEON `null` scalars stay `null`, NEON `null` lists become `[]` (33 `changeLogs`, 14 `specs`, 49 `siteCodes`, 153 `biorepositoryCollections` of 202 products are `null`); (6) polygons are omitted unless asked (`hasPolygon: bool`); (7) every output model is a `ToolResultBase` subclass published as `outputSchema`; handlers return model instances, the registry dumps them.

### 4.1 Common (`models/common.py`, `projections/common.py`, `neon/months.py`)

```python
class NeonInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True,
                              alias_generator=AliasGenerator(validation_alias=lambda n: AliasChoices(n, to_camel(n))))
class NeonOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)     # dumped by_alias=True by the registry
    budget_list: ClassVar[str | None] = None            # name of the list field fit_to_budget may shorten
    budget_elide_fields: ClassVar[tuple[str, ...]] = () # item fields nulled (from the tail) before items are dropped

class Page(NeonOutput):
    total: int | None; returned: int; offset: int; limit: int; truncated: bool
    next_offset: int | None; truncated_reason: Literal["limit", "budget"] | None = None
class Resolved(NeonOutput): field: str; input: str; code: str; confidence: float
class Source(NeonOutput): endpoints: list[str]; via: Literal["graphql", "rest", "local", "mixed"]; cached: bool; derived: list[str] = []
class ToolResultBase(NeonOutput):
    resolved: list[Resolved] = []; notes: list[str] = []; next_steps: list[str] = []; source: Source | None = None

# projections/common.py
def clip_text(s: str | None, budget: int) -> tuple[str | None, bool]
def paginate(items: Sequence[T], *, offset: int, limit: int, total: int | None = None) -> tuple[list[T], Page]
def null_list(v: Iterable[T] | None) -> list[T]
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float
def parse_gcs_expiry(url: str) -> str | None          # X-Goog-Date + X-Goog-Expires → ISO-8601 UTC
def strip_signature(url: str) -> str                  # drop X-Goog-* params (logs, source)
def team_abbr(product_science_team: str | None) -> str | None
def product_level(product_code: str) -> int
def properties_map(items: Sequence[Mapping[str, Any]] | None) -> tuple[dict[str, Any], list[dict[str, Any]] | None]   # raw kept if a name repeats

# neon/months.py (immutable; stores sorted (start_idx, end_idx) int pairs, idx = year*12 + month-1)
class MonthRanges:
    @classmethod
    def from_months(cls, months: Iterable[str]) -> "MonthRanges"
    @classmethod
    def from_ranges(cls, ranges: Iterable[str]) -> "MonthRanges"
    def ranges(self) -> list[str]                      # ["2016-04/2017-12", "2018-03/2018-03"]
    def months(self) -> list[str]; def count(self) -> int; def first(self) -> str | None; def last(self) -> str | None
    def clip(self, start: str | None, end: str | None) -> "MonthRanges"
    def overlaps(self, start: str | None, end: str | None) -> bool
    def __contains__(self, month: str) -> bool; def __len__(self) -> int; def __bool__(self) -> bool
def month_index(month: str) -> int; def index_month(idx: int) -> str
```

Property tests (hypothesis): `MonthRanges.from_months(m).months() == sorted(set(m))`; `from_ranges(r.ranges()) == r`; `clip` ⊆ original.

### 4.2 Products

```
ProductSummary (~300 B): productCode, productName, productDescription (≤300, productDescriptionTruncated), productStatus,
  productScienceTeamAbbr, productCategory, productHasExpanded, themes[], keywords[] (≤8, keywordsTruncated),
  siteCount, monthRange {start,end}|null, latestRelease|null, score? (query given), matchedOn? ["name","keyword:tower"]

ProductDetail(ToolResultBase): ProductSummary (full description) + productCodeLong, productCodePresentation, productScienceTeam,
  productPublicationFormatType, keywords (all),
  releases: [{release, generationDate, url, productDoi: {url, generationDate}|null}]        (always; ≤ 6)
  availability: {siteCount, totalSiteMonths, monthRange, provisionalSiteMonths: int|null}    (always; provisionalSiteMonths null when served from catalog)
  specsCount: int, changeLogCount: int|null, urls: {portal, api}
  # opt-in sections (present only when included)
  productAbstract?, productDesignDescription?, productStudyDescription?, productSensor?, productRemarks?,
  productBasicDescription?, productExpandedDescription?   (each ≤ text_budget, <field>Truncated flags)
  specs?: [{specId, specNumber, specType, specSize, specDescription, specUrl}]
  changeLogs?: [{id, parentIssueID, issueDate, resolvedDate, dateRangeStart, dateRangeEnd, locationAffected, issue (≤400), resolution (≤400)}], changeLogsPage?: Page
  availabilityRows?: [AvailabilityRow], availabilityPage?: Page
  biorepositoryCollections?: [{collectionCode, collectionName, collectionUrl, collectionContentUrl, collectionDownloadUrl}]
```
`project_product_summary(rec: ProductRecord, *, score=None, matched_on=None) -> ProductSummary`; `project_product_detail(rec: ProductRecord | None, raw: Mapping | None, *, include: frozenset[str], text_budget: int, change_logs_page: tuple[int,int], availability: tuple[list[AvailabilityRow], Page] | None) -> ProductDetail`.

### 4.3 Sites

```
SiteSummary (~220 B): siteCode, siteName, siteDescription (≤300), siteType, siteLatitude, siteLongitude, stateCode, stateName,
  domainCode, domainName, productCount, latestRelease|null, distanceKm? (proximity),
  locationElevation?/locationUtmZone?/locationUtmEasting?/locationUtmNorthing?/locationUtmHemisphere? (include_elevation), score?
SiteDetail(ToolResultBase): SiteSummary (full description) + deimsId, urls {portal, api},
  releases?: [{release, generationDate, url}],
  dataProducts?: [{dataProductCode, dataProductTitle, monthCount, monthRange, ranges[]}], dataProductsPage?: Page,
  location?: {locationElevation, locationUtmEasting, locationUtmNorthing, locationUtmZone, locationUtmHemisphere, locationProperties: {name: value}, activePeriods[]}
```
`project_site_summary(rec: SiteRecord, *, distance_km=None, elevation: Mapping | None = None) -> SiteSummary`; `project_site_detail(raw: Mapping, *, include, products_query, products_page) -> SiteDetail`.

### 4.4 Availability

```
AvailabilityRow: siteCode | dataProductCode (key by mode), name, monthCount, monthRange {start,end}|null,
  ranges: [str]                              (format=ranges; omitted otherwise)
  months: [str]                              (format=months)
  byRelease: {tag: [ranges] | [months] | count}   ("PROVISIONAL" is a key when present)
AvailabilityMatrix(ToolResultBase): mode: "product"|"site"|"cell", productCode?, productName?, siteCode?, siteName?,
  release|null, provisional, window {startMonth, endMonth}|null, format,
  summary: {rowCount, totalSiteMonths, monthRange, releases: [{release, rowCount, siteMonths, monthRange}]},
  rows: [AvailabilityRow] (sorted by key), page
  budget_list = "rows"
```
`build_availability(rows_raw: Sequence[Mapping], *, mode, release, provisional, start, end, format, names: Callable[[str], str | None], offset, limit) -> AvailabilityMatrix`. Measured (B): 80 rows ≈ 2.3 KB as ranges, 15.4 KB worst case, +4 KB with `byRelease`.

### 4.5 Locations

```
LocationSummary (~220 B): locationName, locationType, locationDescription (≤160), siteCode|null, domainCode|null, depth, parent,
  isFieldSite? (SITE fast path), locationDecimalLatitude?, locationDecimalLongitude?, locationElevation?, distanceKm?, detailError?: {code, message}
LocationList(ToolResultBase): roots[], locationType, typesAvailable: {TYPE: count}|null, hierarchyNodesScanned, items: [LocationSummary], page   (budget_list = "items")
LocationDetail(ToolResultBase): locationName, locationDescription, locationType, domainCode, siteCode,
  locationDecimalLatitude, locationDecimalLongitude, locationElevation, locationUtmEasting, locationUtmNorthing, locationUtmHemisphere, locationUtmZone,
  alphaOrientation, betaOrientation, gammaOrientation, xOffset, yOffset, zOffset, offsetLocation: {locationName, locationType}|null,
  activePeriods: [{activatedDate, deactivatedDate}], hasPolygon: bool,
  locationProperties?: {name: value}, locationPropertiesRaw?: [{locationPropertyName, locationPropertyValue}], propertyCount,
  locationPolygon?: {coordinates: [{latitude, longitude, elevation}]},
  locationParent, locationParentUrl, parentChain?: [{locationName, locationType, locationDescription}]   (nearest first, from locationParentHierarchy)
  childrenByType?: {TYPE: count}, children?: [LocationSummary], childrenPage?: Page, hierarchyNodesScanned?,
  locationHistory?: [{current, locationStartDate, locationEndDate, locationDecimalLatitude, locationDecimalLongitude, locationElevation, locationUtmEasting, locationUtmNorthing, locationUtmZone, locationUtmHemisphere, alphaOrientation, betaOrientation, gammaOrientation, xOffset, yOffset, zOffset, locationProperties: {name: value}}] (≤100), historyTruncated
```
`flatten_hierarchy(raw: Mapping, *, location_type: str | None, max_depth: int) -> tuple[list[LocationSummary], dict[str, int], int]` (items, types_available, nodes_scanned); `project_location_summary(raw, *, depth, parent) -> LocationSummary`; `project_location_detail(raw, *, include, children_page, hierarchy_max_depth) -> LocationDetail`; `merge_location_details(items, details: Sequence[Mapping]) -> None`.

### 4.6 Files and downloads

```
FileKind = Literal["data","variables","readme","sensor_positions","eml","science_review_flags","categorical_codes","validation","package","other"]
FileRecord (~220 B without URL / ~750 with): siteCode, month, release, name, kind, table|null, hor|null, ver|null, tmi|null, size, md5|null, crc32c|null, url|null
SiteMonthRow: siteCode, month, release, packageType, generationDate, fileCount, totalBytes
FileListing(ToolResultBase): productCode, package, release|null, includeProvisional, siteCodes[], window {startMonth, endMonth}, detail,
  summary: {siteMonthsRequested, siteMonthsWithData, provisionalSiteMonths, fileCount, totalBytes, releases: [{release, generationDate, siteMonths, fileCount, totalBytes}]},
  siteMonths?: [SiteMonthRow], files?: [FileRecord], packages: [{type, url, requiresTokenHeader: true}] (single-cell), externalData: [{name, type, url}],
  urlExpiresAt|null, urlsElided: bool, curlHint|null (uses $NEON_TOKEN, never the value), page
  budget_list = "files"; budget_elide_fields = ("url",)
DownloadReport(ToolResultBase): downloadDir, requested, files: [{path, name, size, md5Verified, status, error}], totals {files, bytes, seconds}
```
`parse_neon_filename(name) -> ParsedFilename(kind, table, hor, ver, tmi, domain, site, product_code, month, package, timestamp, ext)` — regex over `NEON.D##.SITE.DPx.#####.###[.HOR.VER.TMI].TABLE.YYYY-MM.PACKAGE.TIMESTAMPZ.ext`; `.readme.`/`.variables.`/`sensor_positions`/`.EML.`/`science_review_flags`/`categoricalCodes`/`validation` → the corresponding kind; `.zip` → `package`; non-matching → `other`. `project_file_listing(raw_single: Mapping | None, raw_query: Mapping | None, *, filters, detail, include_urls, offset, limit) -> FileListing`.

### 4.7 Releases and citation

```
ReleaseSummary: release, uuid, generationDate, productCount, artifacts: [{name, type, size, md5, url?}]
ReleaseList(ToolResultBase): items: [ReleaseSummary], latestRelease, page
ReleaseDetail(ToolResultBase): ReleaseSummary + dataProducts?: [{productCode, productName, productDescription (≤300), productDoi}], productsPage?: Page,
  sites?: [{siteCode, siteName, domainCode, stateCode}], product?: ProductDetail-base, site?: SiteDetail-base
Citation(ToolResultBase): see §1.3
```
`project_release_summary(raw, *, include_artifact_urls) -> ReleaseSummary`; `project_release_detail(raw, *, include, product_query, products_page, sites_raw) -> ReleaseDetail`; `build_citation(product_raw: Mapping | None, prototype_raw: Mapping | None, *, release, provisional, accessed_on, fmt, templates: CitationTemplates) -> Citation`.

### 4.8 Taxonomy and samples

```
TaxonPage(ToolResultBase): items: [dict] (NEON keys verbatim: taxonTypeCode, taxonID, acceptedTaxonID, updateDate, dwc:scientificName, dwc:scientificNameAuthorship,
  dwc:taxonRank, dwc:vernacularName, dwc:nameAccordingToID, dwc:kingdom, dwc:phylum, dwc:class, dwc:order, dwc:family, dwc:genus, gbif:subspecies, gbif:variety;
  verbose adds the remaining 31 keys with null ranks dropped), page, filters, fuzzyFallbackUsed   (budget_list = "items")
SampleView: sampleUuid, sampleTag, sampleClass, barcode, archiveGuid, sampleEvents: [{ingestTableName, fields: {smsKey: smsValue}}] (smsFieldEntries kept raw if a key repeats),
  eventsTruncated, parentSampleIdentifiers: [{sampleUuid, sampleTag, sampleClass, barcode, archiveGuid}], childSampleIdentifiers: [same]
SampleViews(ToolResultBase): items: [SampleView], degree|null, identifier: {mode, value, sampleClass?}, page   (budget_list = "items")
SampleClassList(ToolResultBase): see §1.3
```
`project_taxon(raw: Mapping, *, verbose: bool) -> dict`; `project_sample_view(raw, *, events_limit, fields) -> SampleView`.

### 4.9 Prototype datasets

```
PrototypeDatasetSummary (~300 B): uuid, projectTitle, datasetAbstract (≤300), startYear, endYear, version, isPublished, doi: {url, generationDate}|null,
  dataThemes[], scienceTeams[], siteCodes[], fileTypes: [name], keywords[] (≤8), dateUploaded
PrototypeDatasetDetail(ToolResultBase): Summary (full abstract) + projectDescription?, designDescription?, metadataDescription?, studyAreaDescription?, versionDescription?,
  relatedVersions: [{datasetUuid, datasetProjectTitle, datasetVersion}], locations?: [{domain, state, siteCode, siteName, latitude, longitude}],
  publicationCitations?: [{citation, citationIdentifier, citationIdentifierType}], relatedDataProducts?: [{dataProductCode, dataProductName}],
  data: {url, dataLocations: [{path, description}]}, files?: [{name, description, fileName, size, md5, type: {name, description}, url?, urlExpiresAt?}], filesPage?: Page
```
`project_prototype_summary(raw) -> PrototypeDatasetSummary`; `project_prototype_detail(raw, files_raw, *, include, include_urls, text_budget, files_page) -> PrototypeDatasetDetail`.

### 4.10 Size budgets and the truncation contract

Measured defaults (B's table, carried over): `neon_search_products` 25 → ~10 KB (max 100 → 40 KB); `neon_search_sites` 50 → 11 KB; `neon_get_product` base ≈ 4 KB, all text sections ≤ 14 KB, specs ≤ 3 KB, 25 change logs ≤ 10 KB; `neon_get_site` 100 products → 12 KB; `neon_get_availability` 100 rows → 3–20 KB; `neon_find_locations` 50 → 11 KB; `neon_get_location` + 50 children → ≤ 20 KB; `neon_list_files` 50 files with URLs → ≤ 38 KB; `neon_search_taxonomy` 25 → 10 KB (100 verbose → 42 KB, hence the cap); `neon_get_sample` 20 views → 25 KB; `neon_search_prototype_datasets` 25 → 10 KB; `neon_get_document` text 20 000 chars ≈ 20 KB; `neon_graphql` ≤ 50 000 B.

Contract: (1) handlers page with `limit`/`offset` and set `page.truncated`/`nextOffset` (`truncatedReason="limit"`); (2) `registry.fit_to_budget(payload, output_model, max_bytes)` runs after the handler: while the compact JSON exceeds `limits.max_result_bytes`, first null the `budget_elide_fields` of items from the tail (`urlsElided=true`), then pop items from `budget_list`'s tail, rewriting `page.returned/truncated/nextOffset/truncatedReason="budget"` and appending `"Result trimmed to fit {max_bytes} bytes; call again with offset={nextOffset} or a smaller limit"` to `nextSteps`; (3) models without a `budget_list` clip their own long lists in the projection (`*Truncated` flags); (4) still above `limits.hard_max_result_bytes` → `result_too_large` (a test asserts this never fires on fixtures); (5) `neon_graphql` prunes the largest array and reports `truncatedPaths`; (6) `notes[]` is the one place for human-readable caveats.

---

## 5. Module layout and file ownership

Every file has exactly one owner (work package WP1–WP9, §11). `tools/__init__.py` is written once by WP1 with the full sorted import list of all 12 family modules so family owners never touch it.

```
neon-mcp/
├── pyproject.toml  uv.lock  LICENSE  .gitignore  .env.example  config.yaml.example  CHANGELOG.md      WP1
├── README.md  CLAUDE.md  AGENTS.md  zensical.toml                                                     WP8
├── .github/workflows/ci.yml  release.yml                                                             WP1
├── .github/workflows/docs.yml                                                                        WP8
├── .claude/agents/mcp-reviewer.md                                                                    WP1
├── Dockerfile  docker-compose.yml                                                                    WP2
├── scripts/
│   ├── okf_validate.py  gen_llms_txt.py  postbuild_agent_surface.py  gen_tools_reference.py  gen_config_reference.py   WP8
│   └── record_fixtures.py                                                                            WP1   (maintainer tool: live → shrink → scrub; documents the §12 rules)
├── docs/**                                                                                           WP8   (OKF bundle, §9)
├── src/neon_mcp/
│   ├── __init__.py            __version__ = "0.1.0"                                                  WP1
│   ├── __main__.py            argparse CLI → load_config → setup_logging → server.run; --check; --print-config   WP1
│   ├── config.py              pydantic Config + loader (NEON_MCP_/__, NEON_TOKEN fallbacks), model_dump_redacted   WP1
│   ├── errors.py              ErrorCode, ToolError, InputRequired, NeonApiError, map_api_error, redact           WP1
│   ├── logging.py             structlog setup (stderr console / JSON), redact_secrets, request-id binding         WP1
│   ├── context.py             ToolContext, UpstreamStats, Elicited, contextvars, build_tool_context               WP1
│   ├── registry.py            ToolSpec, register_tool, get_registered_tools, invoke, fit_to_budget, request-state codec   WP1
│   ├── server.py              NeonServer (MCP callbacks, tool_definitions, call, build_mcp_server, serve), create_server, run   WP1
│   ├── instructions.py        SERVER_INSTRUCTIONS                                                    WP7
│   ├── models/
│   │   ├── __init__.py  common.py   NeonInput, NeonOutput, Page, Resolved, Source, ToolResultBase, shared Annotated types, FileKind   WP1
│   ├── projections/
│   │   ├── __init__.py  common.py   clip_text, paginate, null_list, haversine_km, parse_gcs_expiry, strip_signature, team_abbr, product_level, properties_map   WP1
│   │   ├── products.py  sites.py  availability.py  releases.py                                      WP4
│   │   ├── locations.py  taxonomy.py  prototype.py                                                   WP5
│   │   ├── data.py  documents.py                                                                     WP6
│   │   └── samples.py                                                                                WP7
│   ├── neon/
│   │   ├── __init__.py                                                                               WP2
│   │   ├── client.py  auth.py  ratelimit.py  cache.py                                                WP2
│   │   ├── months.py  catalog.py  gql_queries.py  gql_guard.py  resolve.py                           WP3
│   │   ├── filenames.py  downloads.py                                                                WP6
│   ├── tools/
│   │   ├── __init__.py            fixed sorted import list of the 12 family modules                   WP1
│   │   ├── core.py                neon_ping                                                          WP1
│   │   ├── graphql.py             neon_graphql                                                        WP3
│   │   ├── products.py  sites.py  availability.py  releases.py                                       WP4   (search/get products; search/get sites; availability; list/get releases + citation)
│   │   ├── locations.py  taxonomy.py  prototype.py                                                   WP5
│   │   ├── data.py  documents.py                                                                     WP6   (neon_list_files, neon_download_files; neon_get_document)
│   │   └── samples.py                                                                                WP7   (neon_list_sample_classes, neon_get_sample + MRTR)
│   ├── resources.py  prompts.py  resources_static/*.md|*.json                                        WP7
│   └── transport/
│       ├── __init__.py  stdio.py  streamable_http.py  healthz.py                                     WP2
└── tests/
    ├── conftest.py  fixture_router.py  helpers/ (asgi harness, schema validation, golden)            WP1
    ├── fixtures/  (the 43 files verbatim + §12 additions)  golden/                                   WP1 (files) — golden/*.json per owner of the test that writes it
    ├── test_config.py  test_errors.py  test_logging_redaction.py  test_registry.py  test_server_adapter.py  test_budget.py  test_smoke.py  test_spec_conformance_2026_07_28.py  test_tools_core.py   WP1
    ├── neon/test_client.py  test_auth.py  test_ratelimit.py  test_cache.py                           WP2
    ├── transport/test_streamable_http.py  test_healthz.py  test_token_passthrough.py  test_stdio_dual_era.py   WP2
    ├── neon/test_months.py  test_catalog.py  test_resolve.py  test_gql_guard.py  tests/tools/test_graphql.py   WP3
    ├── tools/test_products.py  test_sites.py  test_availability.py  test_releases.py  test_citation.py; projections/test_products.py  test_sites.py  test_availability.py  test_releases.py   WP4
    ├── tools/test_locations.py  test_taxonomy.py  test_prototype.py; projections/test_locations.py  test_taxonomy.py  test_prototype.py   WP5
    ├── tools/test_data.py  test_downloads.py  test_documents.py; neon/test_filenames.py  test_download_manager.py; projections/test_data.py   WP6
    ├── tools/test_samples.py  test_resources.py  test_prompts.py  test_instructions.py; projections/test_samples.py   WP7
    ├── test_docs_generation.py                                                                       WP8
    ├── test_integration_meta.py  (every tool has a unit test module and a live test; endpoint coverage; tools/list size)   WP9
    └── live/conftest.py (WP1)  test_live_core.py (WP1)  test_live_catalog.py (WP4)  test_live_locations_taxonomy_prototype.py (WP5)  test_live_data.py (WP6)  test_live_samples.py (WP7)  test_live_graphql.py (WP3)
```

### 5.1 Public interfaces between modules (exact signatures — frozen on day 1 by WP1's stub PR)

```python
# ---- errors.py (WP1) ----
ErrorCode = Literal["invalid_argument", "not_found", "ambiguous_input", "auth_required", "forbidden", "rate_limited",
                    "upstream_error", "upstream_unavailable", "graphql_error", "feature_unavailable", "not_available_in_http_mode",
                    "download_limit_exceeded", "download_denied", "checksum_mismatch", "query_too_large", "result_too_large",
                    "catalog_unavailable", "unknown_tool", "internal_error"]
class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, details: Mapping[str, Any] | None = None, hint: str | None = None) -> None
    code: ErrorCode; message: str; details: dict[str, Any]; hint: str | None
    def to_payload(self) -> dict[str, Any]              # {"error": {"code", "message", "details", "hint"}}
class InputRequired(Exception):
    def __init__(self, *, key: str, message: str, requested_schema: Mapping[str, Any], state: Mapping[str, Any]) -> None
class NeonApiError(Exception):
    status: int; detail: str; path: str; retry_after_s: float | None; data: Any; headers: Mapping[str, str]
def map_api_error(exc: NeonApiError, *, token_sent: bool, requires_token: bool, entity: str | None = None, identifier: str | None = None) -> ToolError
def redact(text: str, secrets: Iterable[str]) -> str

# ---- context.py (WP1) ----
@dataclass
class UpstreamStats:
    requests: int = 0; cache_hits: int = 0; rate_limit_remaining: int | None = None; rate_limit_limit: int | None = None
    identity: Literal["anonymous", "token"] = "anonymous"; endpoints: list[str] = field(default_factory=list)
    def as_meta(self) -> dict[str, Any]                  # io.neon-mcp/upstream block
@dataclass(frozen=True)
class Elicited: responses: Mapping[str, Any]; state: Mapping[str, Any]
@dataclass(frozen=True)
class ToolContext:
    config: Config; client: NeonClient; catalog: Catalog
    transport: Literal["stdio", "http"]; tool_name: str
    token: Token | None; client_capabilities: Mapping[str, Any]; elicitation_supported: bool
    elicited: Elicited | None; request_id: str | None; stats: UpstreamStats; log: structlog.stdlib.BoundLogger
    @property
    def token_source(self) -> Literal["config", "request", "none"]
current_config: ContextVar[Config | None]; current_client: ContextVar[NeonClient | None]; current_catalog: ContextVar[Catalog | None]
current_transport: ContextVar[Literal["stdio", "http"]]; current_request_headers: ContextVar[Mapping[str, str] | None]; current_request_id: ContextVar[str | None]
def build_tool_context(*, tool_name: str, client_capabilities: Mapping[str, Any] | None, elicited: Elicited | None = None,
                       request_id: str | None = None, request_headers: Mapping[str, str] | None = None) -> ToolContext

# ---- registry.py (WP1) ----
Surface = Literal["core", "catalog", "locations", "data", "releases", "taxonomy", "samples", "prototype", "documents", "graphql"]
ToolHandler = Callable[[Any, ToolContext], Awaitable[ToolResultBase]]
@dataclass(frozen=True)
class ToolSpec:
    name: str; title: str; description: str; handler: ToolHandler
    input_model: type[NeonInput]; output_model: type[ToolResultBase]
    surface: Surface; requires_token: bool; token_check: Literal["registry", "handler"]; endpoints: tuple[str, ...]
    transports: frozenset[str]; read_only: bool; destructive: bool; idempotent: bool; open_world: bool; supports_mrtr: bool
def register_tool(name: str, *, title: str, description: str, input_model: type[NeonInput], output_model: type[ToolResultBase],
                  surface: Surface, endpoints: Sequence[str], requires_token: bool = False,
                  token_check: Literal["registry", "handler"] = "registry", transports: Iterable[str] = ("stdio", "http"),
                  read_only: bool = True, destructive: bool = False, idempotent: bool = True, open_world: bool = True,
                  supports_mrtr: bool = False) -> Callable[[ToolHandler], ToolHandler]
    # import-time validation: name ^neon_[a-z_]+$, description ≤ 600 chars and ends with a sentence starting "Next:", model bases
def get_registered_tools(*, transport: str | None = None, downloads_enabled: bool = True) -> list[ToolSpec]   # sorted by name
def get_tool(name: str) -> ToolSpec                     # KeyError → caller maps to unknown_tool
def clear_registry() -> None
async def invoke(spec: ToolSpec, raw_args: Mapping[str, Any] | None, ctx: ToolContext) -> dict[str, Any]
    # validate (ToolError invalid_argument) → fail-fast auth_required (token_check="registry") → handler → model_dump(by_alias, exclude_none, mode="json")
    # → stamp source/notes/nextSteps defaults → fit_to_budget → hard cap
def fit_to_budget(payload: dict[str, Any], output_model: type[ToolResultBase], max_bytes: int) -> dict[str, Any]
def encode_request_state(state: Mapping[str, Any]) -> str          # base64url compact JSON ≤ 16 KiB; refuses keys matching (?i)token|authorization
def decode_request_state(encoded: str, *, expected_tool: str) -> dict[str, Any]   # untrusted → ToolError("invalid_argument"); checks v, tool, size, issuedAt ≤ 1 h

# ---- server.py (WP1) ----
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
TOOLS_LIST_TTL_MS = 300_000; RESOURCES_LIST_TTL_MS = 3_600_000; RESOURCE_READ_STATIC_TTL_MS = 86_400_000
RESOURCE_READ_DERIVED_TTL_MS = 3_600_000; PROMPTS_LIST_TTL_MS = 86_400_000; DISCOVER_TTL_MS = 300_000
META_SURFACE = "io.neon-mcp/surface"; META_REQUIRES_TOKEN = "io.neon-mcp/requiresToken"; META_ENDPOINTS = "io.neon-mcp/endpoints"
META_STDIO_ONLY = "io.neon-mcp/stdioOnly"; META_UPSTREAM = "io.neon-mcp/upstream"; META_RESOURCE_KIND = "io.neon-mcp/kind"
@dataclass
class CallOutcome: payload: dict[str, Any]; is_error: bool; input_required: InputRequired | None; stats: UpstreamStats
class NeonServer:
    def __init__(self, config: Config, *, transport: Literal["stdio", "http"], client: NeonClient, catalog: Catalog) -> None
    @property
    def tools(self) -> list[ToolSpec]                    # filtered per deployment
    def tool_definitions(self) -> list[mcp.types.Tool]
    async def call(self, name: str, args: Mapping[str, Any] | None = None, *, input_responses: Mapping[str, Any] | None = None,
                   request_state: str | None = None, request_headers: Mapping[str, str] | None = None,
                   client_capabilities: Mapping[str, Any] | None = None, request_id: str | None = None) -> CallOutcome
    def build_mcp_server(self) -> mcp.server.Server
    async def serve(self) -> None                        # dispatches to transport.serve_stdio / serve_http
    async def aclose(self) -> None
def create_server(config: Config, *, transport: Literal["stdio", "http"], http_transport: httpx.AsyncBaseTransport | None = None) -> NeonServer
def run(config: Config, transport: str | None = None) -> None

# ---- neon/auth.py, ratelimit.py, cache.py, client.py (WP2) ---- §3.2–3.6 verbatim
# ---- transport/* (WP2) ----
async def serve_stdio(server: NeonServer) -> None
def build_http_app(server: NeonServer) -> starlette.applications.Starlette
async def serve_http(server: NeonServer) -> None
@asynccontextmanager
async def app_lifecycle(server: NeonServer) -> AsyncIterator[None]    # prewarm task group, cache background tasks, aclose — used by serve_http and tests
def transport_security(cfg: ServerConfig) -> TransportSecuritySettings | None
class RequestContextMiddleware:                                       # raw ASGI: request id, token header, contextvars, structlog bind, reset in finally
    def __init__(self, app: ASGIApp, *, server: NeonServer) -> None
async def healthz(request: Request) -> JSONResponse; async def readyz(request: Request) -> JSONResponse

# ---- neon/months.py, catalog.py, gql_queries.py, gql_guard.py (WP3) ---- §3.7, §4.1 verbatim; plus
@dataclass(frozen=True)
class GqlQuery: name: str; document: str; expected_fields: tuple[str, ...]; root: str
def check_expected_fields(query: GqlQuery, payload: Mapping[str, Any]) -> list[str]    # missing → drift
ALLOWED_ROOTS: frozenset[str]
def check_query(query: str, *, max_chars: int, max_depth: int, allowed_roots: frozenset[str]) -> None   # ToolError invalid_argument
def prune_to_budget(data: Any, max_bytes: int) -> tuple[Any, list[str]]   # (data, truncated_paths)
# ---- neon/resolve.py (WP3) ----
async def resolve_product(value: str, ctx: ToolContext, *, field: str = "product") -> tuple[str, Resolved | None]
async def resolve_site(value: str, ctx: ToolContext, *, field: str = "site") -> tuple[str, Resolved | None]
async def resolve_sites(values: Sequence[str], ctx: ToolContext, *, field: str = "site_codes") -> tuple[list[str], list[Resolved]]
def normalize_product_code(text: str) -> str | None
ACCEPT_SCORE = 0.75; ACCEPT_MARGIN = 1.15; MAX_CANDIDATES = 8

# ---- neon/filenames.py, downloads.py (WP6) ----
def parse_neon_filename(name: str) -> ParsedFilename
@dataclass(frozen=True)
class PlannedFile: url: str; name: str; size: int | None; md5: str | None; rel_dir: PurePosixPath; requires_token: bool
@dataclass
class DownloadPlan: files: list[PlannedFile]; total_bytes: int; dest_root: Path; skipped_existing: list[PlannedFile]
class DownloadManager:
    def __init__(self, config: DownloadsConfig, client: NeonClient) -> None
    def plan(self, files: Sequence[PlannedFile], *, dest_subdir: str | None, if_exists: Literal["skip", "error"], max_bytes: int | None) -> DownloadPlan
    async def execute(self, plan: DownloadPlan, *, token: Token | None, stats: UpstreamStats) -> list[DownloadedFile]
    def safe_dest(self, *parts: str) -> Path              # real-path confinement; basename regex ^[A-Za-z0-9._-]+$
def host_allowed(url: str, allowed: Sequence[str]) -> bool   # suffix match, "*." wildcard

# ---- resources.py, prompts.py, instructions.py (WP7) ----
@dataclass(frozen=True)
class ResourceContent: text: str; mime_type: str; ttl_ms: int; kind: Literal["static", "derived"]
def list_resources() -> list[mcp.types.Resource]
def list_resource_templates() -> list[mcp.types.ResourceTemplate]
async def read_resource(uri: str, ctx: ToolContext) -> ResourceContent   # ToolError("not_found") with didYouMean on unknown
@dataclass(frozen=True)
class CitationTemplates: released: str; provisional: str; prototype: str; bibtex: str
def citation_templates() -> CitationTemplates            # parsed once from resources_static/citing_neon_data.md fenced blocks
def list_prompts() -> list[mcp.types.Prompt]
def get_prompt(name: str, arguments: Mapping[str, str] | None) -> mcp.types.GetPromptResult
SERVER_INSTRUCTIONS: str                                 # instructions.py, ≤ 1 200 chars
```

Handler shape (every family):

```python
class SearchProductsIn(NeonInput):
    query: str | None = Field(None, description="Free text: keywords, a product-name fragment, or a product code such as DP1.10003.001.")
    ...
@register_tool("neon_search_products", title="Search NEON data products", description="… Next: call neon_get_availability with a productCode.",
               input_model=SearchProductsIn, output_model=ProductSearchResult, surface="catalog",
               endpoints=["POST /graphql", "GET /products"])
async def neon_search_products(args: SearchProductsIn, ctx: ToolContext) -> ProductSearchResult:
    index = await ctx.catalog.products(release=args.release, token=ctx.token, stats=ctx.stats)
    ...
    return ProductSearchResult(items=..., page=..., facets=..., next_steps=[...], source=Source(endpoints=ctx.stats.endpoints, via=index.source, cached=...))
```

Delivery order: WP1 lands the stub PR (all §5.1 signatures with `NotImplementedError` bodies, the fixture router with the full §12 route table, `models/common.py`, `projections/common.py`) on day 1; WP2 and WP3 unblock the tool packages; WP7 and WP8 work from the registry API and fixture outputs.

---

## 6. Config surface (`config.py`)

Precedence CLI flag > env (`NEON_MCP_<SECTION>__<FIELD>`, lower-cased, `__` descends any depth, comma-split for list fields, scalar coercion) > YAML (`--config`) > defaults. Loader is mesa-mcp's (`_load_yaml`, `_load_env`, `_deep_merge`, `_warn_unknown_keys` for YAML **and** env, `set_active_config/get_active_config`) plus the token fallbacks (D18). `SecretStr` guarantees `repr(config)` shows `**********`; `model_dump_redacted()` renders `api_token: "***"` for `--print-config`.

```python
class RateLimitConfig(BaseModel):
    anonymous_burst: int = 180; anonymous_rps: float = 1.8; token_burst: int = 1800; token_rps: float = 7.2
    low_water: int = 5; max_wait_s: float = 10.0
class RetryConfig(BaseModel):
    max_attempts: int = 3; backoff_base_s: float = 0.5; backoff_max_s: float = 8.0; retry_after_default_s: float = 1.0
class NeonConfig(BaseModel):
    base_url: str = "https://data.neonscience.org/api/v0"
    graphql_url: str = "https://data.neonscience.org/graphql"
    api_token: SecretStr | None = None                  # NEON_MCP_NEON__API_TOKEN; fallback NEON_TOKEN
    token_for_public_endpoints: bool | None = None      # None → True on stdio, False on http (D9)
    user_agent_suffix: str | None = None
    connect_timeout_s: float = 10.0; read_timeout_s: float = 60.0; catalog_read_timeout_s: float = 180.0; download_read_timeout_s: float = 300.0
    max_concurrency: int = 4
    prefer_graphql: bool = True
    graphql_breaker_failures: int = 2; graphql_breaker_cooldown_s: float = 900.0
    rate_limit: RateLimitConfig = RateLimitConfig(); retries: RetryConfig = RetryConfig()

class CacheTTLs(BaseModel):
    catalog: int = 3600; detail: int = 900; locations: int = 21600; releases: int = 21600; taxonomy: int = 86400
    samples_classes: int = 86400; samples_view: int = 60; data: int = 600; prototype: int = 21600; documents: int = 86400
class CacheConfig(BaseModel):
    enabled: bool = True; max_entries: int = 1024; max_index_entries: int = 4
    prewarm: bool | None = None                         # None → True on http, False on stdio
    refresh_ahead: float = 0.1; stale_if_error_s: int = 86400
    ttl_s: CacheTTLs = CacheTTLs()

class LimitsConfig(BaseModel):
    default_limit: int = 50; max_limit: int = 500
    max_result_bytes: int = 50_000; hard_max_result_bytes: int = 200_000
    text_budget_summary: int = 300; text_budget_detail: int = 4000
    max_sites_per_call: int = 30; max_site_months_per_query: int = 500; max_location_roots: int = 20
    graphql_max_query_chars: int = 8000; graphql_max_depth: int = 8; graphql_max_response_bytes: int = 50_000; graphql_hard_max_response_bytes: int = 200_000
    max_document_bytes: int = 25 * 1024 * 1024
    tools_list_max_bytes: int = 48_000                  # tightened by WP9 after measurement (D19)

class DownloadsConfig(BaseModel):
    enabled: bool | None = None                         # None → True on stdio, False on http
    directory: Path = Path("~/neon-downloads")          # expanded + resolved at load; created lazily
    max_files_per_call: int = 50
    max_bytes_per_call: int = 2 * 1024**3
    max_file_bytes: int = 1024**3
    verify_checksums: bool = True
    allowed_hosts: list[str] = ["data.neonscience.org", "storage.googleapis.com", "*.storage.googleapis.com"]

class ServerConfig(BaseModel):
    transport: Literal["stdio", "http"] = "stdio"
    bind_address: str = "127.0.0.1"; bind_port: int = 8080
    public_base_url: str | None = None                  # its host/origin are added to the allow-lists; https:// enables header tokens
    allowed_hosts: list[str] = []; allowed_origins: list[str] = []
    dns_rebinding_protection: bool | None = None        # None → SDK default (auto-on for loopback; on when any allow-list is set)
    json_response: bool = False
    max_request_body_size: int = 1 * 1024 * 1024
    accept_header_token: bool = True                    # HTTP: honour per-request X-API-Token (subject to the TLS gate)
    request_token_header: str = "X-API-Token"
    allow_insecure_header_token: bool = False           # accept header tokens over plain http (dev only)
    share_config_token_over_http: bool = False          # lend the operator token to anonymous HTTP callers (private deployments only)
    tools_list_ttl_ms: int = 300_000
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    instructions_extra: str | None = None

class Config(BaseModel):
    neon: NeonConfig = NeonConfig(); cache: CacheConfig = CacheConfig(); limits: LimitsConfig = LimitsConfig()
    downloads: DownloadsConfig = DownloadsConfig(); server: ServerConfig = ServerConfig()
    def model_dump_redacted(self) -> dict[str, Any]
    def effective_downloads_enabled(self, transport: str) -> bool
    def effective_prewarm(self, transport: str) -> bool
    def effective_token_for_public(self, transport: str) -> bool
```

Env names (complete list generated into `docs/getting-started/configuration.md` by `scripts/gen_config_reference.py`): `NEON_MCP_NEON__API_TOKEN`, `NEON_MCP_NEON__BASE_URL`, `NEON_MCP_NEON__GRAPHQL_URL`, `NEON_MCP_NEON__TOKEN_FOR_PUBLIC_ENDPOINTS`, `NEON_MCP_NEON__PREFER_GRAPHQL`, `NEON_MCP_NEON__MAX_CONCURRENCY`, `NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_RPS`, `NEON_MCP_NEON__RETRIES__MAX_ATTEMPTS`, `NEON_MCP_CACHE__PREWARM`, `NEON_MCP_CACHE__TTL_S__CATALOG`, `NEON_MCP_LIMITS__MAX_RESULT_BYTES`, `NEON_MCP_LIMITS__MAX_SITE_MONTHS_PER_QUERY`, `NEON_MCP_DOWNLOADS__ENABLED`, `NEON_MCP_DOWNLOADS__DIRECTORY`, `NEON_MCP_DOWNLOADS__MAX_FILES_PER_CALL`, `NEON_MCP_SERVER__TRANSPORT`, `NEON_MCP_SERVER__BIND_ADDRESS`, `NEON_MCP_SERVER__BIND_PORT`, `NEON_MCP_SERVER__PUBLIC_BASE_URL`, `NEON_MCP_SERVER__ALLOWED_HOSTS`, `NEON_MCP_SERVER__ALLOWED_ORIGINS`, `NEON_MCP_SERVER__ACCEPT_HEADER_TOKEN`, `NEON_MCP_SERVER__ALLOW_INSECURE_HEADER_TOKEN`, `NEON_MCP_SERVER__SHARE_CONFIG_TOKEN_OVER_HTTP`, `NEON_MCP_SERVER__LOG_LEVEL` (one per field; three-level nesting works by the same `__` split).

`config.yaml.example`:

```yaml
neon:
  # api_token: ""                      # prefer NEON_MCP_NEON__API_TOKEN or NEON_TOKEN; never commit a token
  # token_for_public_endpoints: true   # auto: stdio true / http false
  prefer_graphql: true
  max_concurrency: 4
cache:
  # prewarm: true                      # auto: http true / stdio false
  ttl_s:
    catalog: 3600
    detail: 900
    data: 600
limits:
  max_result_bytes: 50000
  max_site_months_per_query: 500
downloads:
  # enabled: true                      # auto: stdio only
  directory: ~/neon-downloads
  max_files_per_call: 50
  max_bytes_per_call: 2147483648
server:
  transport: stdio                     # stdio | http
  bind_address: 127.0.0.1
  bind_port: 8080
  # public_base_url: https://neon-mcp.example.org   # https:// is what enables per-request X-API-Token
  # allowed_hosts: [neon-mcp.example.org]
  accept_header_token: true
  share_config_token_over_http: false
  log_level: info
```

CLI (`neon-mcp`): `--config PATH`, `--transport {stdio,http}`, `--bind-address`, `--bind-port`, `--log-level`, `--download-dir PATH`, `--no-downloads`, `--prewarm/--no-prewarm`, `--print-config` (redacted YAML, exit 0), `--check` (loads config, builds the client, runs `neon_ping(check_api=true)` in-process, prints `{ok, version, tokenConfigured, apiReachable, rateLimit}` JSON, exit 0/1 — for installers), `--version`. No `--token` flag (tokens on the command line leak into `ps` and shell history). `--help`/`--version` import nothing heavy. Bare `neon-mcp` = stdio.

---

## 7. Spec conformance and transport

### 7.1 Server construction (`server.py::NeonServer.build_mcp_server`, low-level `mcp.server.Server`)

```python
from mcp.server import Server
from mcp.server.caching import CacheHint      # CacheableMethod = Literal['prompts/list','resources/list','resources/read','resources/templates/list','server/discover','tools/list'] (verified)
from mcp import types as t

Server(
    "neon-mcp", version=__version__, title="NEON Data API",
    description="Discover, check availability for, list/download files of, and cite NEON (National Ecological Observatory Network) data.",
    instructions=SERVER_INSTRUCTIONS + (cfg.server.instructions_extra or ""),
    website_url="https://github.com/idss-mesa/neon-mcp",
    cache_hints={
        "tools/list": CacheHint(ttl_ms=cfg.server.tools_list_ttl_ms, scope="public"),
        "resources/list": CacheHint(ttl_ms=RESOURCES_LIST_TTL_MS, scope="public"),
        "resources/templates/list": CacheHint(ttl_ms=RESOURCES_LIST_TTL_MS, scope="public"),
        "resources/read": CacheHint(ttl_ms=RESOURCE_READ_DERIVED_TTL_MS, scope="public"),   # per-read result raises ttl_ms to 24 h for static URIs
        "prompts/list": CacheHint(ttl_ms=PROMPTS_LIST_TTL_MS, scope="public"),
        "server/discover": CacheHint(ttl_ms=DISCOVER_TTL_MS, scope="public"),
    },
    on_list_tools=_on_list_tools, on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources, on_list_resource_templates=_on_list_resource_templates, on_read_resource=_on_read_resource,
    on_list_prompts=_on_list_prompts, on_get_prompt=_on_get_prompt,
)
```

Not wired (deprecated or unneeded): `on_set_logging_level`, `on_roots_list_changed`, `on_subscribe_resource`/`on_unsubscribe_resource`/`on_subscriptions_listen` (lists are static per deployment → no `listChanged`), `on_completion` (0.2 candidate), tasks, sampling, SSE. `on_ping` keeps the SDK default.

`_on_call_tool(ctx: ServerRequestContext, params: t.CallToolRequestParams)`:
1. `spec = get_tool(params.name)` (unknown → `unknown_tool`, `is_error` result; the transport's `Mcp-Name` check remains the only protocol-level failure).
2. `caps = (ctx.meta or {}).get("io.modelcontextprotocol/clientCapabilities")`; request headers from `current_request_headers` (set by the middleware) else `ctx.request.headers` when `ctx.request` is a Starlette request (keeps the adapter correct if mounted without our middleware); `elicited = Elicited(params.input_responses, decode_request_state(params.request_state, expected_tool=spec.name))` when `input_responses` present.
3. `outcome = await self.call(...)` → `registry.invoke`.
4. `InputRequired` → `t.InputRequiredResult(input_requests={key: t.ElicitRequest(method="elicitation/create", params=t.ElicitRequestFormParams(mode="form", message=…, requested_schema=…))}, request_state=encode_request_state(state))`.
5. Otherwise `t.CallToolResult(content=[t.TextContent(type="text", text=json.dumps(payload, separators=(",", ":"), ensure_ascii=False))], structured_content=payload, is_error=outcome.is_error, meta={META_UPSTREAM: outcome.stats.as_meta()})` — the SDK stamps `resultType` and merges `io.modelcontextprotocol/serverInfo` (test asserts both keys; if the SDK overwrote ours, the adapter would instead read the SDK-stamped meta and re-merge — decided at integration, test-guarded).
6. `finally`: contextvars reset (middleware owns HTTP-scoped ones; the adapter only resets what it set).

`tool_definitions()` (sorted by name, filtered by `transports` and `downloads.enabled`): `input_schema = spec.input_model.model_json_schema(by_alias=True, mode="validation")`, `output_schema = spec.output_model.model_json_schema(by_alias=True, mode="serialization")`, both `setdefault("$schema", JSON_SCHEMA_DIALECT)`; `$defs` kept; `format` keywords kept (D34); `t.Tool(name, title, description, input_schema, output_schema, annotations=t.ToolAnnotations(read_only_hint, destructive_hint, idempotent_hint, open_world_hint), meta={META_SURFACE, META_REQUIRES_TOKEN, META_ENDPOINTS, [META_STDIO_ONLY]})`.

Resources: `_on_read_resource` → `ReadResourceResult(contents=[TextResourceContents(uri, text, mime_type)], ttl_ms=content.ttl_ms, cache_scope="public")`; unknown URI → JSON-RPC `-32602` (D32).

### 7.2 MRTR and `requestState`

* Only `neon_get_sample` elicits (D13); `neon/resolve.py` never does. Gate: `ctx.elicitation_supported = "elicitation" in client_capabilities` (false for legacy-era stdio clients without per-request `_meta`) → otherwise `ambiguous_input` with the same candidates.
* `requested_schema`: `{"type":"object","properties":{"choice":{"type":"string","title":"sample_class","description":<message>,"enum":[…≤8]}},"required":["choice"]}`; labels repeated in `message`.
* `requestState`: base64url compact JSON `{v:1, tool, args, field, candidates, issuedAt}` ≤ 16 KiB, **unsigned** (mesa-mcp rationale: it carries only the question, never the token, a filesystem path or an authorization decision; the resumed call re-resolves the token and re-runs everything). `encode_request_state` refuses keys matching `(?i)token|authorization`; `decode_request_state` rejects oversize, non-JSON, wrong `v`, `tool ≠ params.name`, `issuedAt` older than 1 h. On resume the handler re-runs the public lookup and accepts only a fresh candidate.
* The SDK's `RequestStateSecurity(keys, codec, ttl=600, bind_principal, audience)` is an `MCPServer` feature not used with the low-level `Server`; revisit if MRTR ever carries anything sensitive (R15).
* The conformance suite registers a test-only tool `neon__conformance_elicit` (registered in the test module, cleared afterwards; never shipped) so encode/decode/tamper/oversize/expiry paths are exercised even if `neon_get_sample`'s fixtures change.

### 7.3 stdio (`transport/stdio.py`)

```python
async def serve_stdio(server: NeonServer) -> None:
    current_config.set(server.config); current_client.set(server.client); current_catalog.set(server.catalog); current_transport.set("stdio")
    mcp_server = server.build_mcp_server()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())   # dual-era loop; options feed server/discover
    finally:
        await server.aclose()
```
Token resolved per call from config (cheap). Logs → stderr only; a test captures stdout during a tool call and asserts only framing was written.

### 7.4 Stateless Streamable HTTP (`transport/streamable_http.py`) — SDK-built app + one raw ASGI middleware (RESEARCH §3.1)

```python
def build_http_app(server: NeonServer) -> Starlette:
    cfg = server.config
    mcp_server = server.build_mcp_server()
    app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=cfg.server.json_response,
        max_request_body_size=cfg.server.max_request_body_size, host=cfg.server.bind_address,
        transport_security=transport_security(cfg.server),                # None → SDK auto-protects loopback binds only
        custom_starlette_routes=[Route("/healthz", healthz, methods=["GET"]), Route("/readyz", readyz, methods=["GET"])],
    )                                                                     # lifespan (session_manager.run()) already wired by the SDK
    app.add_middleware(RequestContextMiddleware, server=server)          # raw ASGI, outermost
    return app

async def serve_http(server: NeonServer) -> None:
    app = build_http_app(server)
    async with app_lifecycle(server):                                     # prewarm task, cache refresh tasks, aclose — no Starlette internals touched
        config = uvicorn.Config(app, host=cfg.server.bind_address, port=cfg.server.bind_port, log_level=cfg.server.log_level, lifespan="on")
        await uvicorn.Server(config).serve()
```

* `/mcp` is a `Route`, so bare `/mcp` works without a 307 and there is no slash normaliser. `GET /mcp` / `DELETE /mcp` behave as the SDK defines for stateless mode (405); no standalone stream, no event store, no `Mcp-Session-Id`.
* `RequestContextMiddleware` (raw ASGI, not `BaseHTTPMiddleware`): generates/propagates `X-Request-Id`; binds `current_transport="http"`, `current_request_id`, `current_request_headers` (only when `accept_header_token` and `header_token_allowed(config)`; otherwise the token header is dropped and a warning logged once per process); binds `structlog.contextvars` (`request_id`, `path`, `method`); strips `X-API-Token` from anything it logs; resets everything in `finally`. It never rejects a request — no token means public-only access.
* `transport_security(cfg)`: `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=…, allowed_origins=…)` when `allowed_hosts`/`allowed_origins`/`public_base_url` are set or `dns_rebinding_protection=True`; `TransportSecuritySettings(enable_dns_rebinding_protection=False)` when explicitly `False` (behind a proxy that normalises `Host`); `None` otherwise (SDK default: auto-on for `127.0.0.1`/`localhost`/`::1`).
* `/healthz` → `200 {"status":"ok","version":…,"protocolVersion": t.LATEST_PROTOCOL_VERSION,"transport":"http"}` — no cache/upstream inspection. `/readyz` → `200 {"status":"ready","catalog":{"products":"warm","sites":"warm"},"degraded":false,"tokenConfigured":bool}` when prewarm is off or complete; `503 {"status":"warming"}` while prewarming; `200 … "degraded": true` if prewarm failed (server still works lazily). Neither echoes token material beyond the boolean.
* Reverse-proxy notes (docs/deploy): terminate TLS (the NEON token is a bearer secret), forward `Host` unchanged and `X-API-Token`, set `public_base_url` + `allowed_hosts`.

### 7.5 Invariants → tests

| Invariant | Enforced in | Test |
|---|---|---|
| Every `inputSchema`/`outputSchema` has `$schema` = 2020-12 and passes `Draft202012Validator.check_schema` | `tool_definitions()` | `test_every_schema_declares_2020_12_dialect`, `test_schemas_are_valid_2020_12` |
| Every tool has an `outputSchema`, a `title`, `annotations` with all four hints; `read_only_hint` false only for `neon_download_files`; no `destructive` | registry | `test_annotations_present_and_consistent` |
| `_meta` has `surface` ∈ Surface, boolean `requiresToken` (true exactly for `neon_list_files`, `neon_download_files`, `neon_get_sample`), `endpoints: list[str]`; `stdioOnly` only on the download tool | registry | `test_meta_surface_requires_token_endpoints` |
| Endpoint coverage: union of `endpoints` == reachability matrix minus `DOCUMENTED_UNUSED` | test constant | `test_endpoint_reachability_matrix` |
| `tools/list` sorted by name, identical across two calls; stdio list has 20 tools, HTTP 19, stdio with `downloads.enabled=false` 19 | registry | `test_tools_list_sorted_stable_per_deployment` |
| `len(json.dumps(tools/list))` ≤ `limits.tools_list_max_bytes`; descriptions ≤ 600 chars ending in "Next:" | registry | `test_tools_list_size_bound`, `test_descriptions_short_with_next` |
| Names match `^neon_[a-z_]+$`; every input model rejects unknown fields and accepts both alias and attribute names | registry | `test_names_and_alias_acceptance`, `test_unknown_argument_reported` |
| `tools/list`, `resources/list`, `resources/templates/list`, `prompts/list`, `resources/read`, `server/discover` carry `ttlMs`+`cacheScope="public"` | cache_hints/read result | `test_list_results_carry_cache_hints`, `test_resource_read_carries_cache_hint`, `test_server_discover_carries_cache_hint` |
| `server/discover` returns `supportedVersions ∋ LATEST_PROTOCOL_VERSION`, capabilities tools/resources/prompts, non-empty `instructions` | SDK + instructions | `test_server_discover_replaces_handshake` |
| `server.session_manager.stateless is True`; no `Mcp-Session-Id` in either era | `stateless_http=True` | `test_session_manager_is_configured_stateless`, `test_legacy_era_request_establishes_no_session` |
| Three independent `tools/call neon_ping` share no state; each has `resultType:"complete"` and `_meta` with **both** `io.modelcontextprotocol/serverInfo` and `io.neon-mcp/upstream` | SDK + adapter | `test_independent_requests_share_no_state`, `test_result_meta_merges_server_info_and_upstream` |
| `Mcp-Name` ≠ body name → 400 "does not match"; `Mcp-Method` ≠ body method → 400 (-32020); `MCP-Protocol-Version: 2024-11-05` header with a 2026-07-28 body → -32020 | SDK | `test_mcp_name_mismatch_rejected`, `test_mcp_method_mismatch_rejected`, `test_header_body_version_mismatch_is_32020` |
| `_meta` protocolVersion `2030-01-01` → JSON-RPC -32022 | SDK | `test_unsupported_protocol_version_is_32022` |
| Forged `Host` → 421 when allow-listed; allow-listed → 200 | `transport_security` | `test_forged_host_rejected`, `test_allowlisted_host_accepted` |
| `POST /mcp` and `POST /mcp/` both 200, no 307; `GET /mcp` → 405; `GET /sse`, `GET /messages/` → 404 | SDK app | `test_bare_and_slashed_mcp_paths`, `test_get_mcp_is_405`, `test_legacy_sse_routes_absent` |
| `X-API-Token` header over https `public_base_url` → `tokenSource:"request"`; over `http://` with `allow_insecure_header_token=false` → ignored (`"none"`), one warning; the literal token appears nowhere in the response or captured logs | middleware + redaction | `test_header_token_honoured_over_tls`, `test_insecure_header_token_ignored`, `test_token_never_leaks` |
| Config token not lent to anonymous HTTP callers unless `share_config_token_over_http` | `resolve_token` | `test_config_token_not_shared_over_http_by_default` |
| `/healthz` 200 without headers; `/readyz` 503 during a simulated prewarm then 200; `degraded: true` after a failed prewarm | healthz.py | `test_healthz_public_and_secret_free`, `test_readyz_warming_then_ready`, `test_readyz_degraded` |
| MRTR: `neon_get_sample(sample_tag=<2-class fixture>)` with an elicitation-capable `_meta` → `resultType:"input_required"`, form, `requestState` without the token; replay completes; tampered/oversized/expired state → `invalid_argument`; without capability → `ambiguous_input` | adapter | `test_mrtr_sample_class_round_trip`, `test_mrtr_state_tamper_rejected`, `test_mrtr_state_expired_rejected`, `test_mrtr_falls_back_without_elicitation`, `test_conformance_elicit_tool_round_trip` |
| `structuredContent` validates against `outputSchema` for every tool on fixtures; every result ≤ `max_result_bytes`; `result_too_large` never fires on fixtures | fit_to_budget | `test_every_tool_output_matches_schema`, `test_budget_enforced_on_large_fixtures`, `test_hard_cap_never_fires_on_fixtures` |
| Request body over `max_request_body_size` → 413 | SDK | `test_request_body_over_limit_rejected` |
| stdio dual era: a 2026-07-28 client and a 2025-11-25 legacy client both `tools/list` + `neon_ping` via `mcp.shared.memory`; nothing but framing on stdout | stdio | `test_stdio_dual_era`, `test_stdout_carries_only_framing` |
| CI grep: no `sampling/createMessage|create_message|roots/list|list_roots|logging/setLevel|set_level|SseServerTransport|connect_sse|Mcp-Session-Id|/sse|/messages/|initialize\b` in `src/`; `mcp` major == 2 | ci.yml | `spec-conformance` job |

---

## 8. Testing strategy

### 8.1 Hermetic unit tests with recorded fixtures

* `tests/fixtures/` = the 43 `scratchpad/fixtures-small/` files **verbatim** (file name = fixture name) + the hand-written additions of §12.
* `tests/fixture_router.py::FixtureRouter` (WP1): `httpx.MockTransport` handler built from `ROUTES: dict[RouteKey, FixtureSpec]` where `RouteKey = (method, path_template, frozenset(param items))` with wildcard params and GraphQL routes keyed by `operationName`. It (a) asserts `X-API-Token` on token endpoints and returns `data_403.json`/`dataquery_403.json` with `example_403.headers` when missing, (b) replays `example_200.headers` (so `X-RateLimit-*` parsing is exercised), (c) records every request in `router.calls` (tools assert cache hits / call counts / that the token was never sent to `storage.googleapis.com`), (d) **raises `AssertionError("unexpected upstream call …")` for anything unrouted** so a test also proves how many calls a tool makes, (e) accepts `extra_routes` per test. The full default route table is §12.
* Clock/sleep seams everywhere (`RateLimiter`, `TTLCache`, backoff, `issuedAt`): tests advance a fake clock and record sleeps — no real waiting.
* Handlers are tested directly (`await neon_search_products(SearchProductsIn(...), ctx)`) with a `ToolContext` factory; the adapter path via `NeonServer.call()`; the wire via the real ASGI app.
* Token tests use the literal `"unit-test-token-DO-NOT-LOG"` and assert it appears in exactly one place: the outbound `X-API-Token` header captured by the router.
* Golden files under `tests/golden/*.json` for projections (`pytest --update-golden` regenerates).
* Per-tool unit-test checklist (a parametrised meta-test in `test_integration_meta.py` asserts every registered tool has a `tests/tools/test_<family>.py` test that calls it): happy path validates against `outputSchema`; each input filter; paging (`offset`, `truncated`, `nextOffset` chains to a disjoint page); size budget (monkeypatch `max_result_bytes=2000` → `page.truncatedReason="budget"`); token tools → `auth_required` **without any upstream call** (`router.calls == []`); NEON 400/404 → `not_found`; second call is a cache hit; `nextSteps` non-empty; `notes`/`source` present; fuzzy resolution echoes `resolved`; `ambiguous_input` and `not_found`+`didYouMean` paths for every fuzzy field.
* Parity tests: `ProductIndex.from_graphql` vs `from_rest` on the shared products; availability rows GraphQL vs REST; `neon_list_files` single-cell vs query mode normalise to the same `FileRecord` shape.
* Client tests: 429 → `RetryAfter` honoured then success; 5xx backoff with fake clock; low-water sleep on `X-RateLimit-Remaining: 3`; per-identity buckets (anon vs two different tokens); token attached only where §3.2 says; envelope unwrapping incl. `data.validReleases`; 302 resolution; `stream_to_file` checksum mismatch removes the partial; `max_bytes` abort; single-flight (10 concurrent misses → 1 upstream call); refresh-ahead and stale-if-error; GraphQL breaker opens/closes; expected-field drift → REST fallback.
* Download tests: confinement (`../x`, absolute, symlink escape via a real symlinked tmp dir), basename regex, host allow-list, plan caps → `download_limit_exceeded` **before** any transfer (`router.calls` has only the listing call), `.part` cleanup, md5 mismatch, `if_exists` skip/error, http-mode refusal, tool absent from the HTTP list. Download bytes are served by an extra route on `https://storage.googleapis.com/fixture/…` (allowed host) from a synthetic 64 KB blob.
* Hypothesis: `MonthRanges` round-trips; `paginate` invariants; `parse_neon_filename` never raises.

### 8.2 Transport tests

`tests/helpers/asgi.py::AppHarness` (ported from mesa-mcp's `_AppHarness`, lifespan-driving, wrapped in `app_lifecycle(server)`) + `httpx.ASGITransport`. Every HTTP test posts to `/mcp` with `MCP-Protocol-Version: 2026-07-28`, `Mcp-Method`, `Mcp-Name` (tools/call), `Accept: application/json, text/event-stream`, body `params._meta = {"io.modelcontextprotocol/protocolVersion": t.LATEST_PROTOCOL_VERSION, "io.modelcontextprotocol/clientCapabilities": {…}}`, parses JSON or the single SSE frame. Covers §7.5 rows 8–18 plus a `json_response=True` variant and middleware cases (header present/absent, contextvars reset after the request, request-id echo).

### 8.3 Live tests (per tool, opt-in)

`@pytest.mark.live` (`addopts = "-ra -m 'not live'"`; enabled with `NEON_MCP_LIVE=1`). One live test **per tool** (brief §5; meta-test asserts every tool name appears in `tests/live/`): `neon_ping(check_api=true)`; `neon_search_products("bird")` finds `DP1.10003.001`; `neon_get_product("DP1.00001.001", include=["specs"])`; `neon_get_availability(product="DP1.00001.001")` ≥ 40 rows and GraphQL-vs-REST parity for one product; `neon_search_sites(query="Harvard")` → HARV; `neon_get_site("HARV")`; `neon_find_locations(site_codes=["HARV"], location_type="TOWER")` → `TOWER100450`; `neon_get_location("HARV")`; `neon_list_releases()` contains RELEASE-2026; `neon_get_release("RELEASE-2026", include=["sites"])`; `neon_get_citation("DP1.10003.001")`; `neon_search_taxonomy(taxon_type_code="BIRD", limit=2)`; `neon_list_sample_classes(query="bet")`; `neon_search_prototype_datasets(query="reaeration")`; `neon_get_prototype_dataset("07dccab1-…")`; `neon_get_document("NEON.DOC.000780vD")` (HEAD); `neon_graphql(introspect_type="Site")`. Token-only (skip without `NEON_TOKEN`): `neon_list_files` single cell + a 2-site × 2-month query, `neon_get_sample(barcode=…)`, `neon_download_files` of one small file into a tmp dir. Live tests **diff response key sets against the fixtures** and fail with "upstream schema drift"; the GraphQL catalog query asserts every `expected_field`. Also measured and asserted (with generous bounds, feeding D19/D27): compact `tools/list` size, `POST /data/query` body size for 5 sites × 12 months, `/locations/REALM?hierarchy=true&locationType=DOMAIN` size. ≤ 25 requests, serialised, 1 rps pacing. Runs nightly (`schedule`), never on PRs.

### 8.4 CI matrix and coverage

`ci.yml`: job `test` — ubuntu-latest × Python 3.11/3.12/3.13 via `astral-sh/setup-uv` + `uv sync --all-extras --dev`; `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict src/` (**every module, no `continue-on-error`**; `pypdf` typed via `ignore_missing_imports` only for that import), `uv run pytest -q --cov=neon_mcp --cov-report=xml --cov-fail-under=85`; a `macos-latest` 3.12 run of `tests/test_smoke.py tests/tools/test_downloads.py tests/transport/test_stdio_dual_era.py` (path semantics). Job `spec-conformance` (3.13): asserts `importlib.metadata.version("mcp")` major == 2; runs `tests/test_spec_conformance_2026_07_28.py tests/transport/`; the deprecated-feature grep of §7.5; advisory `-W error::DeprecationWarning` run. Job `live-nightly` (`schedule: "17 6 * * *"`, `workflow_dispatch`; secret `NEON_TOKEN`; failures open/update one issue via `actions/github-script`). Coverage gates: total ≥ 85 %; `projections/`, `neon/months.py`, `neon/filenames.py`, `neon/downloads.py`, `neon/resolve.py` 100 % lines; `neon/client.py`+`ratelimit.py`+`cache.py`, `registry.py`, `server.py` ≥ 90 %; `transport/` ≥ 90 %; `__main__.py` excluded except `--check`. `release.yml`: on tag `v*` → `uv build`, PyPI trusted publishing, wheel attached to the GitHub release.

---

## 9. Documentation and repo scaffolding (implements RESEARCH §6; extends the phase-1 scaffold already on disk)

### 9.1 What already exists (phase 1, on disk in `/Users/tswetnam/github/neon-mcp`) and what the docs package (WP8) changes

Existing and **kept** (edit, do not recreate): `zensical.toml` (site_url `https://idss-mesa.github.io/neon-mcp/`, CARC theme features, palette green/teal, full markdown_extensions; its `nav` is the phase-1 subset with a `TODO(phase-2)` comment holding the target nav), `docs/index.md` (root, `okf_version: "0.2"` + title + description only), `docs/log.md` (2026-09-10 creation entry), `docs/getting-started/index.md`, `docs/getting-started/api-token.md` (Guide, `stale_after` set, sources: NEON auth/rate-limiting/myaccount), `docs/about/{index,ai-agents,citing-neon,license}.md`, `docs/assets/{favicon,logo}.svg`, `docs/stylesheets/extra.css`, `docs/llms.txt`, `docs/llms-full.txt`, `scripts/{okf_validate,gen_llms_txt,postbuild_agent_surface}.py` (already adapted: `SECTION_ORDER = getting-started, tools, mcp, deploy, develop, about`; site_url read from zensical.toml), `.github/workflows/docs.yml` (both jobs present; `okf-conformance` still `pip install pyyaml` only with a `TODO(phase-2)`), `AGENTS.md`, `LICENSE`, `.gitignore`.

WP8 must: (1) replace the `nav` with the full target nav from the TODO comment (Home · Getting started · Tools · MCP protocol · Deploy · Develop · About; each group `{ "Contents" = "<section>/index.md" }` first; About keeps ai-agents, citing-neon, license and `{ "Changelog" = "log.md" }`); (2) create every missing file of §9.2; (3) change `docs.yml` `okf-conformance` to `pip install -e ".[docs]"` and add `python scripts/gen_tools_reference.py && python scripts/gen_config_reference.py` to the drift check (`git diff --exit-code docs/llms.txt docs/llms-full.txt docs/tools/reference.md docs/getting-started/configuration.md`), and `deploy` to `pip install -e ".[docs]"` (the reference generators import the package); (4) update `AGENTS.md` commands/editing rules for the two new scripts and the tool-catalogue facts; (5) add `docs/log.md` entries for every section created; (6) regenerate `llms.txt`/`llms-full.txt`; (7) update `docs/about/citing-neon.md` so its `sources` include the NEON data-policy page (`https://www.neonscience.org/data-samples/data-policies-citation`) and its wording matches D23 (it is the docs twin of `neon://guide/citing-neon-data`).

### 9.2 Files (RESEARCH §6.4 verbatim; ✔ = exists in phase 1, ✚ = to create, ✎ = to edit)

```
✎ zensical.toml                          full nav (above); everything else kept
✔ docs/index.md                          root (okf_version "0.2"); ✎ body: link every section with one line (tools, mcp, deploy, develop now exist)
✎ docs/log.md                            add "## 2026-09-DD" entries: Creation of getting-started pages, Tools, MCP protocol, Deploy, Develop sections
✎ docs/llms.txt, docs/llms-full.txt      REGENERATED by scripts/gen_llms_txt.py and COMMITTED (CI fails on drift)
✔ docs/getting-started/index.md          ✎ list all five pages
✚ docs/getting-started/install.md        uv tool install / uvx / pipx / from source; verify with `neon-mcp --version` and `neon-mcp --check`
✚ docs/getting-started/quickstart.md     `claude mcp add …`; neon_ping; neon_search_products("bird"); neon_get_availability; the Appendix-B 5-call trace
✔ docs/getting-started/api-token.md      ✎ align env names (NEON_MCP_NEON__API_TOKEN, NEON_TOKEN fallback), X-API-Token + TLS gate, tools that need a token; keep stale_after
✚ docs/getting-started/clients.md        Claude Code, Claude Desktop, Codex CLI, OpenCode, Antigravity, generic stdio JSON; hosted HTTP (`claude mcp add --transport http neon https://host/mcp --header "X-API-Token: $NEON_TOKEN"`)
✚ docs/getting-started/configuration.md  narrative (YAML / env / CLI / precedence) + GENERATED table between <!-- BEGIN GENERATED CONFIG --> … <!-- END GENERATED CONFIG --> by scripts/gen_config_reference.py (field, env name, type, default, description)
✚ docs/tools/index.md                    section listing
✚ docs/tools/reference.md                FULL tool reference, GENERATED by scripts/gen_tools_reference.py (name, title, description, input table from the pydantic schema, output fields, endpoints, requiresToken, annotations, surface, transports), sorted by name; committed; CI fails on drift
✚ docs/tools/products.md                 neon_search_products, neon_get_product: include[] sections, fuzzy names, facets, status default
✚ docs/tools/sites.md                    neon_search_sites, neon_get_site: proximity, include_elevation cost
✚ docs/tools/locations.md                neon_find_locations, neon_get_location: locationType vocabulary, REALM/DOMAIN guard, 1.17 MB unfiltered site walks, towers recipe
✚ docs/tools/availability-and-data.md    neon_get_availability, neon_list_files, neon_download_files: PROVISIONAL is not a release, provisional defaults, 7-day URLs, detail modes, site-month cap, download confinement
✚ docs/tools/releases.md                 neon_list_releases, neon_get_release, neon_get_citation: six releases, DOIs, why /releases/{tag}/sites is never fetched
✚ docs/tools/taxonomy.md                 neon_search_taxonomy: type-vs-rank rule, exact scientificname + genus fallback, verbose cost, Darwin-Core keys
✚ docs/tools/samples.md                  neon_list_sample_classes, neon_get_sample: identifier modes, MRTR/ambiguous_input, token
✚ docs/tools/prototype-datasets.md       the two prototype tools; theme/team string differences
✚ docs/tools/graphql.md                  neon_graphql guardrails, one __type rule, schema resource
✚ docs/tools/utilities.md                neon_ping, neon_get_document, error codes table and remedies
✚ docs/tools/resources-and-prompts.md    the neon:// resources, three templates, three prompts
✚ docs/mcp/index.md                      section listing
✚ docs/mcp/spec-2026-07-28.md            stateless core as implemented: server/discover, _meta envelope, cache hints (list is per-deployment ⇒ public), resultType, MRTR/requestState rules, header routing, no deprecated features; the §7.5 test table; measured tools/list size (D19)
✚ docs/mcp/transports.md                 stdio vs Streamable HTTP (/mcp, /healthz, /readyz), TransportSecuritySettings, per-request X-API-Token and its TLS gate
✚ docs/deploy/index.md                   section listing
✚ docs/deploy/hosted-http.md             uvicorn behind nginx/Caddy (forward Host + X-API-Token), systemd unit, env file, Dockerfile/compose, health checks, horizontal scaling (stateless; per-process cache), prewarm
✚ docs/deploy/security.md                token handling (share_config_token_over_http, TLS gate), log redaction, DNS-rebinding protection, download-directory confinement, allowed download hosts
✚ docs/develop/index.md                  section listing
✚ docs/develop/architecture.md           module map (§5), registry/adapter, client/cache/catalog/projection layers — mermaid diagram; work packages
✚ docs/develop/adding-tools.md           @register_tool walkthrough with neon_list_releases; input/output models; annotations; fixture + route + test; regenerate reference.md
✚ docs/develop/testing.md                pytest layout, FixtureRouter, golden files, `live` marker, conformance suite, coverage gates
✚ docs/develop/contributing.md           branch/PR rules, ruff/mypy strict, log.md + llms + reference regeneration, two-log policy, versioning, release process
✔ docs/about/index.md
✔ docs/about/ai-agents.md                ✎ verify the exact URL list (llms.txt, llms-full.txt, about/ai-agents/, page + index.md) once the site has all sections
✔ docs/about/citing-neon.md              ✎ D23 wording + data-policy source (type: Policy)
✔ docs/about/license.md
✔ docs/assets/favicon.svg, logo.svg
✔ docs/stylesheets/extra.css
✔ scripts/okf_validate.py                (copy of carc-docs-ref/okf_validate.py; keep)
✔ scripts/gen_llms_txt.py                (adapted; keep)
✔ scripts/postbuild_agent_surface.py     (adapted; keep)
✚ scripts/gen_tools_reference.py         NEW: imports neon_mcp.registry + neon_mcp.tools (no network), renders docs/tools/reference.md deterministically (sorted by name) with OKF frontmatter (type: Reference, generated.by "process:gen_tools_reference", generated.at = latest git commit date touching src/neon_mcp/tools/ or --generated-at ISO flag — never wall-clock); input table = pydantic validation schema by alias (name, type, required, default, description); output fields from the serialization schema; endpoints from _meta; --check mode exits 1 on drift
✚ scripts/gen_config_reference.py        NEW: imports neon_mcp.config, renders the generated block of docs/getting-started/configuration.md (section, field, env var, type, default, description); same determinism rules; --check
✎ .github/workflows/docs.yml             §9.1 (3); triggers/permissions/concurrency/actions versions as in the brief (checkout@v7, setup-python@v6, configure-pages@v6 enablement: true, upload-pages-artifact@v5, deploy-pages@v5)
✎ AGENTS.md                              add the two generators to Commands and Editing rules; describe the tool catalogue and where reference.md comes from
✚ CLAUDE.md                              mesa-mcp house style + fixed decisions (§0) + "Docs follow OKF v0.2" section mirroring idss-mesa/docs rules, pointing at AGENTS.md
✎ pyproject.toml (WP1 file; WP8 supplies the line)  optional-dependency group docs = ["zensical>=0.0.60", "pyyaml"]
✚ README.md                              what it is, quick start, token, client recipes, generated tool table pointer, docs site link, agent surface (https://idss-mesa.github.io/neon-mcp/llms.txt), AGENTS.md
```

Frontmatter on every content page, in this order: `title`, `description` (50–160 chars, plain), `type` (`Guide` | `Tutorial` | `Reference` | `Policy` | `MCP Tool Reference`), `tags`, `generated: {by: "claude/fable-5.1" | "human:<id>" | "process:<script>", at: ISO-8601 Z}`, `sources` (`id`/`resource`/`title`/`author`; load-bearing references cited as `[^id]`), `status` (draft|stable|deprecated), `stale_after` only on pages stating facts NEON/MCP may change (api-token, releases list, SDK versions, rate limits). **Never** `verified:`. Section `index.md` files: no frontmatter, `# Heading` + `* [Title](page.md) - description`. Root `docs/index.md`: only `okf_version`, `title`, `description`. Links relative and plain internally, `{target=_blank}` externally; fenced code with a language; images under `docs/assets/`.

### 9.3 Acceptance criteria (RESEARCH §6.5, verbatim)

1. `python scripts/okf_validate.py docs` → 0 errors (warnings allowed only for the root index's extra keys).
2. `python scripts/gen_llms_txt.py && python scripts/gen_tools_reference.py && git diff --exit-code docs/llms.txt docs/llms-full.txt docs/tools/reference.md` → clean (this design adds `python scripts/gen_config_reference.py` and `docs/getting-started/configuration.md` to the same check).
3. `zensical build --clean --strict` → "No issues found"; `python scripts/postbuild_agent_surface.py site` mirrors every page; `site/robots.txt`, `site/llms.txt`, `site/llms-full.txt`, `site/sitemap.xml` exist; `site/<page>/index.md` exists for every page; `grep 'okf:type' site/getting-started/install/index.html` matches.
4. Every content page has `type`, `title`, `description`, `tags`, `generated`, `sources`; no page has `verified`.
5. `docs/log.md` has the 2026-09-10 creation entry; `docs/about/ai-agents.md` lists the exact URLs under https://idss-mesa.github.io/neon-mcp/.
6. `.github/workflows/docs.yml` passes `actionlint`-level sanity (valid YAML, action versions as listed) and would deploy to the `github-pages` environment on first push to main.

### 9.4 Two-log policy, README, CLAUDE.md, repo files

* **Two logs.** `CHANGELOG.md` (Keep a Changelog, repo root, WP1) is the package release log — `## [0.1.0] - 2026-MM-DD` lists the 20 tools, 8 resources + 3 templates, 3 prompts, transports, conformance suite, "supersedes idss-mesa/neon-data-api TypeScript server (SDK 1.x, spec 2024-11-05)". `docs/log.md` is the OKF §9 log for the documentation bundle only; each release adds one `* **Update**: docs for neon-mcp vX.Y.Z (see CHANGELOG.md)`; `docs/develop/contributing.md` states the rule.
* README outline: what it is + badges (CI, MCP 2026-07-28, docs, PyPI); quick start (`uv tool install neon-mcp`, `uvx neon-mcp --check`, `pipx`); token (what works without one); client recipes — Claude Code stdio `claude mcp add neon -s user -e NEON_TOKEN=… -- uvx neon-mcp --transport stdio` and the venv form (`-- /abs/path/.venv/bin/neon-mcp --transport stdio`, matching `idss-mesa/docs/install.sh`), Claude Code HTTP `claude mcp add --transport http neon https://host/mcp --header "X-API-Token: ${NEON_TOKEN}"`, Claude Desktop / Codex / OpenCode / Antigravity snippets; tool table (pointer to `docs/tools/reference.md`); resources & prompts; configuration pointer; downloads (stdio only); rate limits & caching; docs site + agent surface + AGENTS.md; development, contributing, license, citing NEON data.
* CLAUDE.md outline: purpose; fixed decisions (RESEARCH §0 + this §0); NEON facts (token endpoints, 400-for-not-found, PROVISIONAL is not a release, rate limits, payload sizes, GraphQL gaps); naming rules (D1); module ownership map (§5/§11); how to add a tool (decorator → projection → fixture route → test → `gen_tools_reference.py`); testing rules (no network in unit tests, `live` marker, fixture scrubbing, FixtureRouter unexpected-call rule); security rules (token never logged/echoed/in requestState/sent to third-party hosts; download confinement); **Docs follow OKF v0.2** (frontmatter rules, `index.md` no frontmatter, `log.md` entries, regenerate llms + reference + config; never `verified:`; see AGENTS.md); release process.
* Repo files (WP1 unless noted): `LICENSE` (exists), `.gitignore` (exists; add `site/`, `neon-downloads/`, `tests/fixtures/_raw/`, `.coverage*`, `htmlcov/`, `config.yaml`, `.env`; `uv.lock` committed), `.env.example` (`NEON_MCP_NEON__API_TOKEN=` or `NEON_TOKEN=`, transport/bind/port, downloads dir, `NEON_MCP_LIMITS__MAX_RESULT_BYTES=50000`, log level, precedence comment, never-commit warning), `config.yaml.example` (§6), `Dockerfile`/`docker-compose.yml` (WP2: `python:3.13-slim`, `uv`, non-root, `HEALTHCHECK /healthz`, `CMD ["neon-mcp","--transport","http","--bind-address","0.0.0.0"]`), `pyproject.toml`: `[project] name="neon-mcp"`, dynamic version from `src/neon_mcp/__init__.py`, `requires-python=">=3.11"`, MIT, authors "IDSS / MESA contributors, University of New Mexico", keywords `mcp neon neonscience ecology data-api model-context-protocol`, classifiers (Alpha, Science/Research, MIT, 3.11–3.13, Scientific/Engineering); `dependencies=["mcp>=2.0,<3","httpx>=0.28,<1","pydantic>=2.7","pyyaml>=6","structlog>=24","anyio>=4","starlette>=0.40","uvicorn>=0.30"]`; extras `pdf=["pypdf>=4"]`, `docs=["zensical>=0.0.60","pyyaml"]`, `dev=["pytest","pytest-asyncio","pytest-cov","hypothesis","jsonschema","ruff","mypy","types-PyYAML"]`; `[project.scripts] neon-mcp="neon_mcp.__main__:main"`; `[project.urls]` Homepage/Documentation (`https://idss-mesa.github.io/neon-mcp/`)/Source/Issues/Changelog; hatch wheel `packages=["src/neon_mcp"]` (static resources are package data); ruff `line-length=100`, `target-version="py311"`, `select=["E","F","I","UP","B","SIM","S","RUF"]` (`S` for the download path; per-file-ignores for tests); pytest `asyncio_mode="auto"`, `testpaths=["tests"]`, `markers=["live: hits the real NEON API (opt-in)"]`, `addopts="-ra -m 'not live'"`; coverage `fail_under=85`; mypy `strict=true`, `python_version="3.11"`, `plugins=["pydantic.mypy"]`. `.claude/agents/mcp-reviewer.md` adapted from mesa-mcp (checklist: §7.5 invariants, token hygiene, size budgets, fixture route + test present, docs regenerated). Versioning SemVer from `0.1.0`, tags `v0.1.0`.

---

## 10. Risks and open questions — with resolutions

| # | Risk / question | Resolution (decided) |
|---|---|---|
| R1 | GraphQL is "metadata" per NEON and can drift (`productScienceTeamAbbr` already undefined) | `gql_queries.py` pairs each query with `expected_fields`; a missing field / `errors` / timeout → REST fallback + warning with the diff; circuit breaker after 2 failures; `indexSource`/`source.via`/`neon_ping.catalog` show which path is live; the recorded `graphql_products_compact.json` ValidationError is the unit test; the nightly live test asserts every expected field. |
| R2 | GraphQL lacks `productScienceTeamAbbr`, `productCategory`, `productCodeLong`, `productCodePresentation`, `productSensor`, `changeLogs`, `biorepositoryCollections` | Derive the first four (string forms verified; unit-tested against all REST records in `products.json`/raw); REST detail on demand for the rest; `source.derived` lists them. |
| R3 | REST fallback parses a 30 MB JSON (~150–300 MB peak) | Rare path; single-flight + semaphore; project immediately and drop raw; `catalog_read_timeout_s`; document ~1 GiB memory request for hosted; streaming parser only if measurements demand. |
| R4 | Signed URLs (7-day expiry) may be cached/copied | `urlExpiresAt` on every listing; `data` TTL 10 min; downloads re-list rather than accept URLs; guides say never paste URLs into citations. |
| R5 | Per-request token passthrough serves many users' tokens through one deployment | TLS gate (D10); tokens never logged/cached in clear/in `requestState`/echoed; token-endpoint cache keyed by `identity()`; `share_config_token_over_http=false`; per-identity rate buckets. |
| R6 | Download safety (traversal, symlinks, SSRF via redirect, disk fill) | Basename regex, real-path confinement, host suffix allow-list on every redirect hop (≤ 3), per-call/per-file byte caps computed before transfer, `.part` + `os.replace`, stdio only, absent from HTTP list, no arbitrary-URL selector. |
| R7 | `POST /data/query` response size for wide windows is unmeasured | D27 cap (500 site-months) + `query_too_large`; WP9 measures 5 × 12 and 30 × 24 live and sets the default from the data; `detail="summary"` is the planner mode for anything wide. |
| R8 | Agents pass `release="PROVISIONAL"` (old server accepted it) | `ReleaseTag` rejects locally with a message naming `provisional`/`include_provisional`; docs and `neon://reference/graphql-schema` state the rule. |
| R9 | Provisional months visible in availability but not fetchable | D28: consistent include defaults; `notes` count provisional site-months; every file row carries `release`. |
| R10 | `tools/list` size with 20 tools × two schemas × `$defs` | D19: test bound at 48 KB initially, real measurement in WP9, threshold tightened; descriptions ≤ 600 chars; guidance in resources. |
| R11 | Hosted anonymous deployments share one per-IP quota (200/2 rps) | Aggressive caching of public endpoints; per-request tokens bring the user's own quota; `rate_limited` carries `retryAfterSeconds`; `_meta` upstream block shows remaining budget; docs recommend requiring tokens at the proxy for many users. |
| R12 | Taxonomy `verbose`/`stream` payloads are large; `scientificname` is exact-match | `stream` never sent; verbose caps `limit` at 100 and drops null ranks; genus fallback with `fuzzyFallbackUsed`. The "400 no data" claim is unverified: an empty page is modelled as `count: 0` and the live test records what NEON actually returns. |
| R13 | Unfiltered hierarchy walks (`HARV` 1.17 MB, REALM unknown) | D26 guards; SITE roots cached 6 h; `hierarchyNodesScanned` + `notes`; WP9 measures `/locations/REALM?hierarchy=true&locationType=DOMAIN` and one domain walk live. |
| R14 | GraphQL `locationHierarchy(name, locationType)` might beat REST | Unverified → REST for hierarchies in 0.1; a live test compares the two for HARV/TOWER; switch in 0.2 if identical and smaller. |
| R15 | MRTR client support is uneven; `requestState` is client-controlled and unsigned | Only `neon_get_sample`; capability-gated with `ambiguous_input` fallback; state holds only the question, size-capped, re-validated, 1 h expiry; revisit signing if state ever carries more. |
| R16 | Fuzzy resolution picks the wrong site/product silently | Accept only ≥ 0.75 and ≥ 1.15× runner-up; always echo `resolved` with `confidence`; exact codes bypass fuzzy logic; adversarial pairs (`Blue River` vs `Blue Ridge`, `wind` products) in tests. |
| R17 | Result `_meta` merge: does the SDK overwrite our `meta` when stamping `serverInfo`? | Test `test_result_meta_merges_server_info_and_upstream` decides; if the SDK overwrites, the adapter re-merges after the SDK hook (WP9 verifies against mesa-mcp's current idiom). |
| R18 | Resource-not-found exception class in `mcp` 2.x | D32: `-32602`; WP9 confirms the 2.x class from mesa-mcp `server.py` (no `McpError(-32002)`). |
| R19 | pydantic alias mechanics: `AliasChoices` first choice must be what `model_json_schema(by_alias=True)` emits; `NeonOutput` must dump camelCase | `test_names_and_alias_acceptance` and `test_output_dumps_camel_case` guard it; if a pydantic version differs, `NeonInput` switches to explicit `Field(validation_alias=…)` per field with the same test. |
| R20 | Change logs up to 539 per product; `null` lists | Off by default, paged 25/200, clipped; `null_list()` everywhere; the raw fixture set includes such products. |
| R21 | `/locations/sites` has 88 SITE locations vs 81 field sites | `isFieldSite=false` for codes absent from the sites catalog; `neon_search_sites` uses `/sites` only. |
| R22 | mesa-mcp's venv has `mcp` 2.0.0, brief pins facts to 2.2.0 | Every SDK surface used was verified on 2.0.0 and matches RESEARCH §3 for 2.2.0; `mcp>=2.0,<3`; conformance job asserts major == 2; advisory `DeprecationWarning` run. |
| R23 | Legacy-era stdio clients (2024-11-05…2025-11-25) | SDK dual-era loop; `create_initialization_options()` retained; `test_stdio_dual_era`; only `elicitation_supported` depends on per-request `_meta` (false without it). |
| R24 | Citation wording drift | Templates in a resource (D23), sourced to NEON's data-policy page in OKF `sources`; live test resolves one DOI; guide points at `neonUtilities::getCitation` for authoritative DataCite output. |
| R25 | Prototype theme/team strings differ from products (`Land Cover and Processes`, `Aquatic Observational Systems (AOS)`) | Prefix/abbreviation matching; facets show exact upstream strings; documented in `docs/tools/prototype-datasets.md`. |
| R26 | Per-process caches under multiple replicas | Accepted (≈ 3 MB/index, 1 h TTL, prewarm); shared cache out of scope until measured need. |
| R27 | Windows | `pathlib`, `~` expansion at load, `os.replace`; CI ubuntu + macOS; Windows "expected to work, not gated" in 0.1. |
| R28 | `neonutilities` overlap | Out of scope (brief §5); `nextSteps` after downloads suggest `pandas.read_csv` and mention `neonutilities.stack_by_table`; a future extra could add a stacking tool without touching existing files. |

---

## 11. Implementation work packages

Nine packages. Every file in §5 has exactly one owner; packages code against the §5.1 signatures and can start concurrently once WP1's day-1 stub PR lands (signatures with `NotImplementedError` bodies, `models/common.py`, `projections/common.py`, `tests/fixture_router.py` with the §12 route table, `tests/fixtures/*`). WP9 is the final integration package.

### WP1 — Core platform and test harness
* **Owns**: `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `config.yaml.example`, `CHANGELOG.md`, `.github/workflows/ci.yml`, `release.yml`, `.claude/agents/mcp-reviewer.md`, `scripts/record_fixtures.py`; `src/neon_mcp/{__init__,__main__,config,errors,logging,context,registry,server}.py`, `models/{__init__,common}.py`, `projections/{__init__,common}.py`, `tools/__init__.py`, `tools/core.py`; `tests/conftest.py`, `tests/fixture_router.py`, `tests/helpers/*`, `tests/fixtures/*` (43 verbatim + WP1-owned additions of §12), `tests/test_config.py`, `test_errors.py`, `test_logging_redaction.py`, `test_registry.py`, `test_server_adapter.py`, `test_budget.py`, `test_smoke.py`, `test_spec_conformance_2026_07_28.py`, `test_tools_core.py`, `tests/live/conftest.py`, `tests/live/test_live_core.py`.
* **Consumes**: `NeonClient`/`Catalog` constructor signatures (WP2/WP3) for `create_server`; `transport.serve_stdio/serve_http/app_lifecycle` (WP2) for `serve()`.
* **Ships tests**: config precedence + env parsing (incl. `RATE_LIMIT__`, `NEON_TOKEN` fallback, redaction, unknown-key warnings); error mapping table (every row of §3.5 incl. 400-not-found and `validReleases`); redaction processor; registry validation (name/description/model bases), sorted definitions, per-deployment filtering, `invoke` fail-fast auth, alias + attribute acceptance, `fit_to_budget` (elide-then-drop, `truncatedReason`, `nextSteps` line, hard cap), request-state codec (refused keys, size, expiry, tool mismatch); `NeonServer.call` for ToolError/InputRequired/success; the full §7.5 conformance list (with the test-only `neon__conformance_elicit` tool); `neon_ping` unit + live.
* **Acceptance**: stub PR merged day 1; `pytest tests/test_spec_conformance_2026_07_28.py` green against `neon_ping` alone; `mypy --strict` clean; `neon-mcp --version`, `--print-config`, `--check` work; CI workflows valid.

### WP2 — NEON client, auth, rate limiting, cache, transports
* **Owns**: `src/neon_mcp/neon/{__init__,client,auth,ratelimit,cache}.py`, `src/neon_mcp/transport/{__init__,stdio,streamable_http,healthz}.py`, `Dockerfile`, `docker-compose.yml`; `tests/neon/test_client.py`, `test_auth.py`, `test_ratelimit.py`, `test_cache.py`, `tests/transport/test_streamable_http.py`, `test_healthz.py`, `test_token_passthrough.py`, `test_stdio_dual_era.py`.
* **Consumes**: `Config` models, `ErrorCode`/`NeonApiError`/`ToolError`, `UpstreamStats`, contextvars, `NeonServer.build_mcp_server()/config/catalog` (WP1); `Catalog.prewarm()/warmth()` (WP3) for `/readyz` and `app_lifecycle`.
* **Ships tests**: §8.1 client list (429/5xx/low-water/per-identity buckets/token placement/envelope/302/stream_to_file/single-flight/refresh-ahead/stale-if-error); `resolve_token` matrix (stdio; http × {https, http, allow_insecure} × {header, config, share}); `Token` repr redaction; §7.5 transport rows (stateless, no session id both eras, cache hints, discover, host 421, `/mcp` + `/mcp/`, `GET /mcp` 405, `/sse` 404, header token honoured/ignored, token never leaks, `/healthz`, `/readyz` 503→200→degraded, request-id echo, contextvars reset, `json_response=True`, body limit 413); stdio dual era + stdout framing only.
* **Acceptance**: `NeonClient` passes the FixtureRouter suite with zero real sleeps; `serve_http` runs under uvicorn with `/healthz` 200; `mypy --strict` clean; no Starlette internals touched (grep `lifespan_context` finds nothing).

### WP3 — Catalog, months, resolution, GraphQL guard and tool
* **Owns**: `src/neon_mcp/neon/{months,catalog,gql_queries,gql_guard,resolve}.py`, `src/neon_mcp/tools/graphql.py`; `tests/neon/test_months.py`, `test_catalog.py`, `test_resolve.py`, `test_gql_guard.py`, `tests/tools/test_graphql.py`, `tests/live/test_live_graphql.py`.
* **Consumes**: `NeonClient.graphql/get_json` + `TTLCache` + `Token` (WP2); `ToolError`, `Resolved`, `ToolContext` (WP1).
* **Ships tests**: hypothesis round-trips for `MonthRanges`; `ProductIndex.from_graphql` vs `from_rest` parity on the 6 shared products (derived fields, null `siteCodes`, facets); `SiteIndex` search/nearest/fuzzy (`"Harvard"` → HARV; adversarial pairs); ranking table; `expected_fields` drift → REST fallback + breaker open/close; `resolve_*` exact/fuzzy/ambiguous/not_found (never elicits); `check_query` (mutation rejected, root allow-list, depth, one `__type`, `BadFaithIntrospection` mapping); `prune_to_budget` paths; `neon_graphql` never sends a token, never cached; live: catalog expected fields, `introspect_type="Site"`.
* **Acceptance**: catalog builds from `graphql_products_catalog.json` and from `products.json` with identical `records`; `neon_graphql` schema validates; 100 % lines on `months.py`/`resolve.py`.

### WP4 — Catalog tools: products, sites, availability, releases, citation
* **Owns**: `src/neon_mcp/tools/{products,sites,availability,releases}.py`, `src/neon_mcp/projections/{products,sites,availability,releases}.py`; `tests/tools/test_products.py`, `test_sites.py`, `test_availability.py`, `test_releases.py`, `test_citation.py`, `tests/projections/test_{products,sites,availability,releases}.py` + their golden files, `tests/live/test_live_catalog.py`.
* **Consumes**: `Catalog.*`, `MonthRanges`, `resolve_*` (WP3); `Token`, `UpstreamStats` (WP2); `registry.register_tool`, `Page`, `paginate`, `clip_text`, `ToolResultBase` (WP1); `resources.citation_templates()` (WP7 — stubbed in tests until WP7 lands).
* **Ships tests**: per-tool checklist (§8.1) for the 7 tools; `neon_get_product(include=[])` served locally when warm (`router.calls == []` after warm-up) and from REST for sections; `release=` scoping (`product_DP1.00001.001_RELEASE-2025.json`); availability product/site/cell modes, local clipping of `availableReleases` (PROVISIONAL months outside the window disappear), `provisional` include/exclude/only, `format` variants, GraphQL vs REST parity; search facets/status default/`didYouMean`; `neon_get_release` products/artifacts/sites (GraphQL codes-only; never routes to `/releases/{tag}/sites`), uuid → tag, `product_code`/`site_code` sub-resources, `release_400_not_found.json` → `not_found` + `validReleases`; citation text/BibTeX exact strings for RELEASE-2026 DOI, provisional wording, cross-check note, `not_found` + `availableReleases`; live tests for all 7 tools.
* **Acceptance**: every output validates against its `outputSchema`; measured default result sizes recorded in `docs/tools/*` inputs for WP8; 100 % lines on the four projection modules.

### WP5 — Locations, taxonomy, prototype
* **Owns**: `src/neon_mcp/tools/{locations,taxonomy,prototype}.py`, `src/neon_mcp/projections/{locations,taxonomy,prototype}.py`; `tests/tools/test_locations.py`, `test_taxonomy.py`, `test_prototype.py`, `tests/projections/test_{locations,taxonomy,prototype}.py` + golden, `tests/live/test_live_locations_taxonomy_prototype.py`; fixture additions `location_REALM_hierarchy_DOMAIN.json`, `location_TOWER100450.json`, `location_HARV_history.json`, `taxonomy_empty.json`, `taxonomy_400_conflict.json`.
* **Consumes**: `Catalog.site_locations/locations_batch/prototype_datasets/sites` + `resolve_sites` (WP3); `NeonClient.get_json` (WP2); WP1 core.
* **Ships tests**: REALM/DOMAIN guard (`invalid_argument`, no upstream call); SITE fast path with `isFieldSite`; DOMAIN fast path; TOWER pruning (68 nodes → depth/paging); unfiltered site walk → `typesAvailable` from the same payload (`router.calls` has exactly one call), `hierarchyNodesScanned`; coordinate hydration via `findLocations` with REST fan-out fallback and per-item `detailError`; `neon_get_location` include combinations, `parentChain`, properties map + raw on duplicates, history; taxonomy type-vs-rank validation, paging from `next`, verbose null-drop and cap, genus fallback with `fuzzyFallbackUsed`; prototype search filters/facets (`is_published`), detail includes, `urlExpiresAt` null-safety; live tests for the 5 tools.
* **Acceptance**: never requests `/locations/REALM?hierarchy=true` without `locationType` (asserted by the router); 100 % lines on the three projection modules.

### WP6 — Data listing, downloads, documents
* **Owns**: `src/neon_mcp/tools/{data,documents}.py`, `src/neon_mcp/neon/{filenames,downloads}.py`, `src/neon_mcp/projections/{data,documents}.py`; `tests/tools/test_data.py`, `test_downloads.py`, `test_documents.py`, `tests/neon/test_filenames.py`, `test_download_manager.py`, `tests/projections/test_data.py` + golden, `tests/live/test_live_data.py`; fixture additions `dataquery_DP1.00001.001_ABBY_HARV.json`, `data_file_302.headers`, `documents_HEAD_NEON.DOC.000780vD.headers`, `download_small.bin` + `.md5`.
* **Consumes**: `NeonClient.get_json/post_json/resolve_redirect/head/fetch_bytes/stream_to_file`, `Token`, `require_token` (WP2); `resolve_product/resolve_sites`, `Catalog.product_detail/products` (WP3); `parse_gcs_expiry`, `Page`, `FileKind` (WP1).
* **Ships tests**: filename grammar table (≥ 25 real names incl. IS/OS/AOP/readme/variables/sensor_positions/EML/zip); single-cell vs query endpoint choice, normalised `FileRecord` parity, `detail` modes, filters, URL elision before record drop, `urlExpiresAt`, `filename=` 302 resolution, site-month cap → `query_too_large` with no upstream call, provisional notes; `DownloadManager.plan` caps before transfer, confinement/symlink/basename/host tests, `.part` cleanup, md5 mismatch, `if_exists` skip/error, layout paths, prototype and document selectors without a token, HTTP refusal and absence from the list; documents HEAD metadata, spec lookup, in-memory pypdf extraction on a generated 2-page PDF, `feature_unavailable` when pypdf is missing, char paging; live: single cell, 2×2 query, download of one small file (token).
* **Acceptance**: `neon_list_files` without a token makes zero upstream calls; the plan test proves `router.calls` contains only the listing before `download_limit_exceeded`; 100 % lines on `filenames.py`/`downloads.py`.

### WP7 — Samples (MRTR), resources, prompts, instructions
* **Owns**: `src/neon_mcp/tools/samples.py`, `src/neon_mcp/projections/samples.py`, `src/neon_mcp/resources.py`, `src/neon_mcp/prompts.py`, `src/neon_mcp/instructions.py`, `src/neon_mcp/resources_static/*`; `tests/tools/test_samples.py`, `tests/projections/test_samples.py`, `tests/test_resources.py`, `test_prompts.py`, `test_instructions.py`, `tests/live/test_live_samples.py`; fixture addition `samples_download_degree2.json`.
* **Consumes**: `InputRequired`, `Elicited`, `ToolContext.elicitation_supported`, `registry.invoke/get_tool` (templates), `NeonServer` constants (WP1); `Catalog.sample_classes/sites/releases` (WP3); `NeonClient.get_json`, `require_token` (WP2).
* **Ships tests**: identifier-mode validation; classes lookup → one class proceeds, two classes → `InputRequired` when capable else `ambiguous_input`; resume with a fresh candidate / stale candidate rejected; `degree` routing; events fold + `eventsTruncated` + `fields`; `samples_classes_404` → empty list not error; every resource URI reads with the right `ttl_ms`/`kind`; `citation_templates()` parses the four fenced blocks; templates resolve through `invoke`; unknown URI → `not_found` with `didYouMean`; prompts render with/without optional args and validate arguments; `SERVER_INSTRUCTIONS` ≤ 1 200 chars and mentions the token rule; live: `neon_list_sample_classes`, `neon_get_sample(barcode=)` (token).
* **Acceptance**: `neon://reference/vocabularies` lists every enum used by input models (a test cross-checks `Literal` values against the JSON); MRTR conformance rows pass against `samples_classes_ok.json`.

### WP8 — Documentation bundle (RESEARCH §6.4; extends the phase-1 scaffold)
* **Owns**: everything in §9.2 — `zensical.toml`, `docs/**` (all pages, `llms.txt`, `llms-full.txt`, `log.md`, assets, stylesheets), `scripts/okf_validate.py`, `scripts/gen_llms_txt.py`, `scripts/postbuild_agent_surface.py`, `scripts/gen_tools_reference.py`, `scripts/gen_config_reference.py`, `.github/workflows/docs.yml`, `AGENTS.md`, `CLAUDE.md`, `README.md`; `tests/test_docs_generation.py`.
* **Consumes**: `registry.get_registered_tools()` + `tool_definitions()`-equivalent schema rendering (WP1) for `reference.md`; `config.Config` model fields (WP1) for the configuration table; measured sizes and worked examples from WP4–WP7 result fixtures; the phase-1 files on disk.
* **Ships tests**: `test_docs_generation.py` — `gen_tools_reference.py --check` and `gen_config_reference.py --check` are deterministic (two runs identical; `--generated-at` honoured; no wall-clock), every registered tool appears in `reference.md`, every `docs/tools/<family>.md` mentions each tool of its family, `okf_validate.py docs` returns 0.
* **Acceptance**: the six §9.3 criteria; `zensical build --clean --strict` prints "No issues found"; `docs.yml` `okf-conformance` job passes locally (`pip install -e ".[docs]"` + the four scripts + `git diff --exit-code`); `docs/log.md` has entries for every new section; `about/ai-agents.md` URL list verified against the built `site/`.

### WP9 — Integration and reconciliation (final)
* **Owns**: `tests/test_integration_meta.py`; the final content of `src/neon_mcp/tools/__init__.py` import list (WP1 file, WP9 reconciles); `CHANGELOG.md` `[0.1.0]` entry (WP1 file, WP9 writes); threshold constants `limits.tools_list_max_bytes`, `limits.max_site_months_per_query` defaults after measurement (WP1 file, WP9 edits with the measured values); the `docs/mcp/spec-2026-07-28.md` "measured" paragraph (WP8 file, WP9 supplies the numbers).
* **Consumes**: everything.
* **Ships tests**: meta-tests — every registered tool has a unit test module invoking it and a live test; endpoint reachability matrix equality (`io.neon-mcp/endpoints` ∪ == matrix − `DOCUMENTED_UNUSED`); `tools/list` byte size with real `$defs`; every output model has `budget_list` or documented self-clipping; Appendix B five-call trace as an end-to-end test over fixtures (search → availability → list_files → download_files (tmp dir) → citation); the whole suite green on 3.11/3.12/3.13 and macOS.
* **Reconciliation checklist**: run `mypy --strict` and `ruff` over the merged tree; confirm SDK 2.x facts left open (R17 `_meta` merge, R18 exception class, R19 pydantic alias/schema behaviour, `Mcp-Method` mismatch enforcement) and fix the adapter/tests accordingly; live-measure `tools/list` bytes, `POST /data/query` (5 × 12 and 30 × 24), `/locations/REALM?hierarchy=true&locationType=DOMAIN`, one domain walk, the GraphQL catalog query size — record them in `docs/mcp/spec-2026-07-28.md` / `docs/tools/availability-and-data.md` and set the final defaults; regenerate `reference.md`, `configuration.md`, `llms*.txt`; tag `v0.1.0`.
* **Acceptance**: `uv run pytest` (unit + conformance) green; `NEON_MCP_LIVE=1 uv run pytest -m live` green with a token; `docs.yml` and `ci.yml` green on the first push to `main`; `neon-mcp --check` exits 0.

---

## 12. Fixture plan

`tests/fixtures/` receives the 43 files of `scratchpad/fixtures-small/` **verbatim** (same names). The default `FixtureRouter` route table is this section; GraphQL routes are keyed by `operationName`. "Owner" is the work package that ships the tests named.

### 12.1 The 43 existing fixtures → routes → tests

| Fixture | Route (default) | Content that matters | Used by (tests) |
|---|---|---|---|
| `example_200.headers` | replayed on every 2xx | `x-ratelimit-limit: 200`, `remaining: 200`, `reset: 1` | WP2 `test_ratelimit` (observe), all tools (`_meta` upstream) |
| `example_403.headers` | replayed on 403 | `remaining: 197` | WP2 `test_client` |
| `rate_limited_429.json` | any route when a test sets `router.inject_429(n)` (+ `rate_limited_429.headers`, WP2 addition: `RetryAfter: 1`) | `{"message":"API rate limit exceeded"}` | WP2 `test_ratelimit`, `test_client` |
| `products.json` | `GET /products` | 6 products: `DP1.00001.001` (ACTIVE TIS 3 sites), `DP1.00007.001` (**FUTURE, `siteCodes: null`**), `DP1.10003.001` (TOS), `DP1.20001.001` (AOS, 0 sites), `DP1.20002.001` (AIS), `DP1.30001.001` (AOP) | WP3 `test_catalog` (REST build, parity, null lists, derived fields), WP4 `test_products` (facets, status default, level) |
| `product_DP1.00001.001.json` | `GET /products/DP1.00001.001` | 3 sites (ABBY, ARIK, BARC), 6 months each incl. `PROVISIONAL`+`RELEASE-2026` splits, 2 changeLogs, 2 specs, releases 2025/2026 | WP4 `test_products` (sections, change-log paging), `test_availability` (REST fallback + clipping), `test_citation` (cross-check), WP6 `test_documents` (spec lookup) |
| `product_DP1.00001.001_RELEASE-2025.json` | `GET /products/DP1.00001.001?release=RELEASE-2025` | `releases == [RELEASE-2025]` | WP4 `test_products` (release scoping) |
| `product_DP1.10003.001.json` | `GET /products/DP1.10003.001` | DOIs `10.48443/3nka-yg96` (2025), `10.48443/v6hs-mx57` (2026); sites ABBY/BARR/BART | WP4 `test_citation` (exact strings, `latest`), `test_products` |
| `product_404.json` | `GET /products/DP9.99999.999` → **400** | `"Product code not found"` | WP1 `test_errors`; WP4 `test_products` (`not_found` + `didYouMean`) |
| `sites.json` | `GET /sites` | ABBY, HARV, SRER (5 products each) | WP3 `test_catalog` (REST sites build, fuzzy "Harvard" → HARV, nearest), WP4 `test_sites` |
| `site_ABBY.json`, `site_HARV.json` | `GET /sites/ABBY`, `GET /sites/HARV` | 5 dataProducts × 6 months; deimsId; releases | WP4 `test_sites` (get_site includes, products paging), `test_availability` (site-mode fallback) |
| `site_404.json` | `GET /sites/ZZZZ` → 400 | `"Site code not found"` | WP1 `test_errors`; WP4 `test_sites` |
| `locations_sites.json` | `GET /locations/sites` | 3 SITE locations (ABBY, HARV, SRER) | WP5 `test_locations` (REALM+SITE fast path, `isFieldSite`), WP4 `test_sites` (`include_elevation`) |
| `location_HARV.json` | `GET /locations/HARV` | 36 properties, 5 children, no history, no polygon | WP5 `test_locations` (get_location properties/children), WP4 `test_sites` (`include=["location"]`) |
| `location_HARV_hierarchy.json` | `GET /locations/HARV?hierarchy=true` | 6 child nodes (types CONFIG, `OS Plot - all`, `OS Plot - bet`, Point); parent chain D01 → REALM (FIELD) | WP5 (unfiltered SITE walk → `typesAvailable`, `hierarchyNodesScanned`, `parentChain`) |
| `location_HARV_hierarchy_TOWER.json` | `GET /locations/HARV?hierarchy=true&locationType=TOWER` | 68 nodes: TOWER100450 → LEVEL → BOOM → CONFIG | WP5 (TOWER pruning, depth cap, paging) |
| `location_D01.json` | `GET /locations/D01` | DOMAIN, 3 children | WP5 (domain detail; REALM/DOMAIN guard uses **no** route) |
| `location_404.json` | `GET /locations/NOPE_NOT_A_LOCATION` → 400 | `"Location not found."` | WP1 `test_errors`; WP5 |
| `data_DP1.00001.001_ABBY_2023-01.json` | `GET /data/DP1.00001.001/ABBY/2023-01?package=basic` (token) | 3 files (`2DWSD_30min` data, readme, variables), `packages[]` basic/expanded URLs, `release: RELEASE-2025`, signed URLs `…X-Goog-Signature=REDACTED` | WP6 `test_data` (single cell, filename grammar, `packages`, `urlExpiresAt`), `test_downloads` (plan) |
| `data_403.json` | same path without token → 403 | `"Access Denied"` | WP1 `test_errors` (`auth_required`/`forbidden`), WP2 `test_client`; router default when the header is missing |
| `dataquery_DP1.00001.001_ABBY.json` | `POST /data/query` `{productCode: DP1.00001.001, siteCodes: [ABBY], startDateMonth: 2023-01, endDateMonth: 2023-02, …}` (token) | 1 release, 2 site-months, 1 file each | WP6 `test_data` (query mode, `site_months`/`summary` detail, FileRecord parity) |
| `dataquery_403.json` | `POST /data/query` without token → 403 | | WP1, WP2, router default |
| `releases.json` | `GET /releases` (and `GET /releases/{uuid}` alias → `release_RELEASE-2025.json`) | RELEASE-2025, RELEASE-2026 (+ uuids, MANIFEST artifacts) | WP4 `test_releases` (`latestRelease`, artifact URLs off/on, uuid → tag), WP7 `test_resources` (`neon://reference/releases`) |
| `release_RELEASE-2025.json` | `GET /releases/RELEASE-2025` | 5 dataProducts with bare `productDoi` URLs, artifacts | WP4 `test_releases` (products paging/query), `test_citation` (cross-check) |
| `release_RELEASE-2025_product_DP1.00001.001.json` | `GET /releases/RELEASE-2025/products/DP1.00001.001` | product as published in the release (all REST keys) | WP4 `test_releases` (`product_code=`) |
| `release_RELEASE-2025_products.json` | **no route** (payload hazard) | | WP9 `test_integration_meta` asserts no tool declares this endpoint |
| `release_RELEASE-2025_sites.json` | **no route** (payload hazard; `include=["sites"]` goes to GraphQL) | | WP4 asserts the router never sees it; WP9 |
| `graphql_sites_compact.json` | `POST /graphql` op `NeonMcpSitesForRelease` | siteCode/siteName/siteType/domain/state/lat/lon | WP4 `test_releases` (`include=["sites"]`) |
| `graphql_products_compact.json` | `POST /graphql` op `NeonMcpProductsCatalog` **only when** `router.drift_catalog=True` | `ValidationError FieldUndefined productScienceTeamAbbr` | WP3 `test_catalog` (drift → REST fallback, breaker) |
| `graphql_filterProducts_availability.json` | op `NeonMcpProductAvailability` (productCodes `[DP1.00001.001]`, siteCodes, `2023-01..2023-06`) | `availableMonths` windowed; `availableReleases` **unclipped** (PROVISIONAL 2025-07..2026-08) | WP4 `test_availability` (product mode, local clipping, provisional modes) |
| `graphql_filterSites_availability.json` | op `NeonMcpSiteAvailability` (siteCodes `[ABBY]`, productCodes `[DP1.00001.001]`, `2024-01..2024-03`) | 3 months | WP4 `test_availability` (site mode) |
| `graphql_findLocations.json` | op `NeonMcpLocations` (`[HARV, TOWER104454, D01]`) | lat/lon/elevation; DOMAIN with nulls | WP5 `test_locations` (hydration, null-safety) |
| `graphql_error.json` | any unrouted `POST /graphql` user query (`neon_graphql`) | `ValidationError` on `nope` | WP3 `test_graphql` (`graphql_error` mapping, errors-with-null-data) |
| `taxonomy_BIRD_p1.json` | `GET /taxonomy?taxonTypeCode=BIRD&verbose=false&offset=0&limit=5` | `count 5, total 2244, next → offset=5` | WP5 `test_taxonomy` (paging from `next`, 17 compact keys verbatim) |
| `taxonomy_BIRD_verbose.json` | `…&verbose=true&offset=0&limit=2` | 48 keys | WP5 (null-rank drop, verbose cap 100) |
| `taxonomy_genus_Quercus.json` | `GET /taxonomy?genus=Quercus&verbose=false&offset=0&limit=5` | 5 Quercus names | WP5 (rank query; genus fallback second step) |
| `samples_supportedClasses.json` | `GET /samples/supportedClasses` | 8 `{key, value}` entries | WP7 `test_samples` (`neon_list_sample_classes` query filter) |
| `samples_classes_ok.json` | `GET /samples/classes?sampleTag=A00000123456` | **2 classes** | WP7 (MRTR ambiguity → `InputRequired` / `ambiguous_input`; resume) ; WP1 conformance MRTR rows |
| `samples_classes_404.json` | `GET /samples/classes?sampleTag=NOPE` → 404 | "No Sample Classes Found…" | WP7 (empty list, not error) |
| `samples_view_barcode.json` | `GET /samples/view?barcode=A00000123456` (token) | 1 view, 2 events | WP7 `test_samples` (fields fold, `eventsTruncated`, `fields=`) |
| `prototype_datasets.json` | `GET /prototype/datasets` | 3 datasets (all `isPublished: false`) | WP5 `test_prototype` (search, `is_published` filter, facets) |
| `prototype_dataset_07dccab1.json` | `GET /prototype/datasets/07dccab1-4990-4d2f-9c5b-bf97e10517e3` | all keys | WP5 (detail includes), WP4 `test_citation` (`prototype_uuid`) |
| `prototype_data_07dccab1.json` | `GET /prototype/data/07dccab1-…` | 2 files (EML xml 15 KB, zip 4.6 MB) on `neon-publication-proto.storage.googleapis.com` | WP5 (files), WP6 `test_downloads` (prototype selector without token; `*.storage.googleapis.com` allow-list) |

### 12.2 Additional hand-written fixtures (all ≤ 10 KB; signatures `REDACTED`; owner records them in `tests/fixtures/MANIFEST.md`)

| Fixture | Owner | Shape / source | Tests |
|---|---|---|---|
| `graphql_products_catalog.json` | WP1 | `PRODUCTS_CATALOG` response for the same 6 products as `products.json`, derived by `scripts/record_fixtures.py --derive-gql-catalog products.json` (deterministic transform: keep the §3.7 selection, `releases{productDoi}`, `specs`, `siteCodes{siteCode availableMonths}`); the scratchpad's raw `gql_products.json` cannot be used (it lacks `releases`/`specs`) | WP3 parity + default catalog route |
| `graphql_sites_catalog.json` | WP1 | `SITES_CATALOG` response for ABBY/HARV/SRER derived from `sites.json` (adds `deimsId`, `releases{release}`, `dataProducts{dataProductCode dataProductTitle}`) | WP3, WP4 sites tools |
| `release_400_not_found.json` | WP1 | `{"error":{"status":400,"detail":"Release not found. See data response element for valid releases."},"data":{"validReleases":["RELEASE-2021","RELEASE-2022","RELEASE-2023","RELEASE-2024","RELEASE-2025","RELEASE-2026"]}}` routed at `GET /releases/RELEASE-1999` and `GET /products/DP1.00001.001?release=RELEASE-1999` | WP1 `test_errors`, WP4 `test_releases`/`test_products` |
| `graphql_bad_faith_introspection.json` | WP3 | `{"errors":[{"message":"…","extensions":{"classification":"BadFaithIntrospection"}}]}` | WP3 `test_graphql` (`invalid_argument`) |
| `location_REALM_hierarchy_DOMAIN.json` | WP5 | REALM (type FIELD) with 20 DOMAIN children `D01`–`D20` and their descriptions | REALM+DOMAIN fast path |
| `location_TOWER100450.json` | WP5 | minimal REST `Location` record (name, type TOWER, siteCode HARV, lat/lon/elevation, parent) | REST hydration fallback |
| `location_HARV_history.json` | WP5 | `GET /locations/HARV?history=true` with 2 `locationHistory` entries | `include=["history"]` |
| `taxonomy_empty.json` | WP5 | `{"count":0,"total":0,"prev":null,"next":null,"data":[]}` at `GET /taxonomy?scientificname=Quercus%20agrifolia&…` (shape assumed; the live test records NEON's real empty response) | genus fallback first step |
| `taxonomy_400_conflict.json` | WP5 | `{"error":{"status":400,"detail":"Taxon type code and taxon rank parameters must not both be specified"},"data":null}` | mapping only (validator prevents the call) |
| `dataquery_DP1.00001.001_ABBY_HARV.json` | WP6 | `POST /data/query` for `[ABBY, HARV]` × `2023-01..2023-02`, two `releases[]` blocks (`RELEASE-2025`, `PROVISIONAL`), ≤ 2 files per package | `summary`/`site_months` detail, provisional notes, release-desc ordering |
| `data_file_302.headers` | WP6 | `HTTP/2 302` + `Location: https://storage.googleapis.com/neon-publication/…?X-Goog-Date=20260910T000000Z&X-Goog-Expires=604800&X-Goog-Signature=REDACTED` at `GET /data/DP1.00001.001/ABBY/2023-01/NEON.D16.ABBY.DP1.00001.001.readme.20250128T000000Z.txt` | `filename=` resolution, `urlExpiresAt` |
| `documents_HEAD_NEON.DOC.000780vD.headers` | WP6 | `200`, `content-type: application/pdf`, `content-disposition: attachment; filename="NEON.DOC.000780vD.pdf"`, `content-length: 3553655` | `neon_get_document` metadata |
| `download_small.bin` + `download_small.md5` | WP6 | synthetic 64 KB blob served at `https://storage.googleapis.com/fixture/download_small.bin` | DownloadManager stream/md5/caps |
| (in-test) 2-page PDF | WP6 | generated with `pypdf` at test time, served at `GET /documents/NEON.DOC.TEST01vA` | text extraction/paging |
| `samples_download_degree2.json` | WP7 | 3 views with parent/child identifiers, ≤ 3 events each | `degree=2` |
| `rate_limited_429.headers`, `error_500.txt` | WP2 | `RetryAfter: 1`, `x-ratelimit-remaining: 0`; an HTML 500 body | retry/backoff/non-JSON mapping |

Rules (`scripts/record_fixtures.py --check` enforces them in CI): no `X-Goog-Signature=` other than `REDACTED`, no `apiToken=`, no occurrence of any recording token, every fixture ≤ 40 KB, every fixture referenced by a route exists and vice versa, total ≤ 3 MB.

---

### Appendix A — `SERVER_INSTRUCTIONS` (server/discover), ≤ 1 200 chars

> neon-mcp exposes the NEON (National Ecological Observatory Network) Data API. Typical flow: `neon_search_products` (fuzzy keywords) → `neon_get_availability` (which sites/months have data, released vs PROVISIONAL) → `neon_list_files` (needs a NEON API token; returns signed URLs valid ~7 days; `detail="summary"` sizes a pull first) → `neon_download_files` (stdio only, writes under the configured download directory) → `neon_get_citation`. Product and site fields accept codes (`HARV`, `DP1.10003.001`) or names (`"Harvard Forest"`, `"breeding landbird"`); confident matches are echoed in `resolved`, ambiguous ones return `ambiguous_input` with candidates. `PROVISIONAL` is not a release tag — use the `provisional`/`include_provisional` switches. Every result is compact and paginated (`page.nextOffset`), carries `notes`, and ends with `nextSteps`. Call `neon_ping` to learn whether a token is configured; without one, all discovery, availability, taxonomy, release, location and prototype tools still work. Read `neon://guide/agent-workflow` for worked examples and `neon://reference/vocabularies` for valid filter values.

### Appendix B — worked agent trace (end-to-end acceptance test in WP9; target 5 calls)

1. `neon_search_products(query="breeding bird point counts")` → `DP1.10003.001 Breeding landbird point counts` (`matchedOn: ["name","keyword:birds"]`), `nextSteps: ["neon_get_availability(product='DP1.10003.001')", …]`.
2. `neon_get_availability(product="DP1.10003.001", domain_code="D01")` → rows for BART, HARV with `ranges: ["2015-06/2015-06", "2016-06/2025-06"]`, `byRelease` incl. `PROVISIONAL`, `notes: ["2 provisional site-months included; pass provisional='exclude' to drop them"]`.
3. `neon_list_files(product="DP1.10003.001", site_codes=["Harvard Forest"], start_month="2023-06", kind="data")` → `resolved: [{field:"site_codes", input:"Harvard Forest", code:"HARV", confidence:0.97}]`, 3 files (`brd_countdata`, `brd_perpoint`, `brd_references`) with URLs and `urlExpiresAt`.
4. `neon_download_files(product="DP1.10003.001", site_codes=["HARV"], start_month="2023-06", kind="data")` → 3 files under `~/neon-downloads/DP1.10003.001/HARV/2023-06/`, `md5Verified: true`, `nextSteps: ["pandas.read_csv('…brd_countdata…csv')"]`.
5. `neon_get_citation(product="DP1.10003.001")` → text + BibTeX with the RELEASE-2026 DOI `10.48443/v6hs-mx57`.
