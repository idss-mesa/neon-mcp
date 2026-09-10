---
title: "Install neon-mcp"
description: "Install the neon-mcp server with uv or pip from GitHub (or PyPI once released), verify it with --version and --check, and run it from source."
type: Guide
tags:
  - getting-started
  - install
  - uv
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: uv
    resource: "https://docs.astral.sh/uv/"
    title: "uv documentation"
    author: "team:astral"
  - id: repo
    resource: "https://github.com/idss-mesa/neon-mcp"
    title: "neon-mcp source repository"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# Install neon-mcp

neon-mcp is a Python 3.11+ package with one command, `neon-mcp`. The recommended
installer is [uv](https://docs.astral.sh/uv/){target=_blank}[^uv], which keeps the
server in its own environment.

!!! note "PyPI release"

    Until the first PyPI release, install from GitHub as shown below. After it,
    `uv tool install neon-mcp` and `uvx neon-mcp` work directly.

=== "uv tool (recommended)"

    ```bash
    uv tool install git+https://github.com/idss-mesa/neon-mcp
    uv tool install "neon-mcp[pdf] @ git+https://github.com/idss-mesa/neon-mcp"   # with PDF text extraction
    ```

    This puts `neon-mcp` on your `PATH` (`~/.local/bin`). Upgrade with
    `uv tool upgrade neon-mcp`.

=== "uvx (no install)"

    ```bash
    uvx --from git+https://github.com/idss-mesa/neon-mcp neon-mcp --version
    ```

=== "pipx / pip"

    ```bash
    pipx install git+https://github.com/idss-mesa/neon-mcp
    # or, inside a virtual environment:
    pip install "git+https://github.com/idss-mesa/neon-mcp"
    ```

=== "From source"

    ```bash
    git clone https://github.com/idss-mesa/neon-mcp
    cd neon-mcp
    uv sync --all-extras          # creates .venv with the package and dev tools
    uv run neon-mcp --version
    ```

    MCP clients can then run `/absolute/path/to/neon-mcp/.venv/bin/neon-mcp`.

## Verify

```bash
neon-mcp --version     # neon-mcp 0.1.0
neon-mcp --check       # {"ok": true, "version": "0.1.0", "tokenConfigured": false, "apiReachable": true, ...}
```

`--check` loads your configuration, makes one small anonymous NEON request and
exits 0 when NEON is reachable. `--print-config` shows the effective settings with
the token masked.

Next: [connect a client](clients.md) and [add your NEON API token](api-token.md).

[^uv]: uv documentation. <https://docs.astral.sh/uv/>
[^repo]: neon-mcp source repository. <https://github.com/idss-mesa/neon-mcp>
