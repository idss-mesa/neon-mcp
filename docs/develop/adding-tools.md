---
title: "Adding a tool"
description: "A walkthrough of adding a neon-mcp tool: input and output models, registration, annotations, a fixture route, tests and docs regeneration."
type: Tutorial
tags:
  - develop
  - tools
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: registry
    resource: "https://github.com/idss-mesa/neon-mcp/blob/main/src/neon_mcp/registry.py"
    title: "neon-mcp registry (registry.py)"
    author: "team:idss-mesa"
status: stable
---

# Adding a tool

`neon_list_releases` is the smallest real example; this is its shape.

## 1. Models

```python
class ListReleasesIn(NeonInput):          # snake_case fields; camelCase accepted; extras rejected
    include_artifact_urls: bool = Field(False, description="Include signed manifest URLs.")


class ReleaseList(ToolResultBase):        # envelope: resolved, notes, nextSteps, source
    items: list[ReleaseSummary]
    latest_release: str | None = None     # dumped as latestRelease
    page: Page
```

Every input field needs a `description` (it is what the model reads). Output keys use
NEON's own camelCase names where NEON has the field. Long lists declare
`budget_list` so results can be trimmed to the size budget.

## 2. Register the handler

```python
@register_tool(
    "neon_list_releases",
    title="List NEON data releases",
    description="... Next: call neon_get_release for one release's products and DOIs.",
    input_model=ListReleasesIn,
    output_model=ReleaseList,
    surface="releases",
    endpoints=["GET /releases"],
)
async def neon_list_releases(args: ListReleasesIn, ctx: ToolContext) -> ReleaseList:
    releases = await ctx.catalog.releases(token=ctx.token, stats=ctx.stats)
    ...
```

Rules the registry enforces at import: names match `^neon_[a-z_]+$`, descriptions are
at most 600 characters and end with a `Next:` sentence. Declare `requires_token=True`
for token-only endpoints (the registry then fails fast without one), keep annotations
honest, and list every NEON endpoint the handler calls. Import the module from
`tools/__init__.py`.

## 3. Fixtures and tests

Add recorded, shrunk, scrubbed responses to `tests/fixtures/` and routes to
`tests/fixture_router.py` (unrouted requests fail the test). Test through
`tests.helpers.call_ok`, which also validates the result against the tool's
`outputSchema`: happy path, each filter, paging, error mapping, token fail-fast, cache
reuse.

## 4. Regenerate

```bash
python scripts/gen_tools_reference.py      # docs/tools/reference.md
python scripts/gen_llms_txt.py             # docs/llms.txt, docs/llms-full.txt
```

Mention the tool on its family page and add a `docs/log.md` entry.
