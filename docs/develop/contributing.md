---
title: "Contributing"
description: "Branch and pull-request rules, lint and type checks, documentation regeneration, the two change logs, versioning and releases."
type: Policy
tags:
  - develop
  - contributing
  - releases
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: keepachangelog
    resource: "https://keepachangelog.com/en/1.1.0/"
    title: "Keep a Changelog 1.1.0"
    author: "team:keepachangelog"
  - id: semver
    resource: "https://semver.org/"
    title: "Semantic Versioning"
    author: "team:semver"
status: stable
---

# Contributing

1. Branch from `main`; open a pull request. CI must be green.
2. Before pushing:

    ```bash
    uv run ruff check src tests scripts && uv run ruff format --check src tests
    uv run mypy --strict src
    uv run pytest
    python scripts/record_fixtures.py check
    python scripts/gen_tools_reference.py && python scripts/gen_config_reference.py
    python scripts/gen_llms_txt.py && python scripts/okf_validate.py docs
    ```

3. Documentation follows OKF v0.2 (see `AGENTS.md`): frontmatter on every content page,
   no frontmatter on section `index.md` files, a dated entry in `docs/log.md`, and the
   generated files committed.

## Two change logs

* `CHANGELOG.md` (repository root) is the package release log, in the Keep a
  Changelog format[^keepachangelog].
* `docs/log.md` is the OKF log of the documentation bundle; each release adds one
  "docs for neon-mcp vX.Y.Z" entry.

## Versioning and releases

neon-mcp follows Semantic Versioning[^semver] from 0.1.0. The version lives in
`src/neon_mcp/__init__.py`. Pushing a `vX.Y.Z` tag runs `.github/workflows/release.yml`:
tests, `uv build`, PyPI trusted publishing and a GitHub release with the artifacts.

[^keepachangelog]: Keep a Changelog 1.1.0. <https://keepachangelog.com/en/1.1.0/>
[^semver]: Semantic Versioning. <https://semver.org/>
