---
okf_version: "0.2"
title: neon-mcp
description: "neon-mcp is a Model Context Protocol (MCP 2026-07-28) server that gives AI agents structured, rate-limit-aware access to the NEON Data API."
---

# neon-mcp

**neon-mcp** is a [Model Context Protocol](https://modelcontextprotocol.io/){target=_blank}
server for the [NEON Data API](https://data.neonscience.org/data-api/){target=_blank}.
It lets AI agents and coding assistants discover NEON data products, sites and
locations, check data availability by site and month, browse releases,
taxonomy and prototype datasets, and — with a NEON API token — list and fetch
data files, all through compact, size-bounded tool results instead of the
API's multi-megabyte raw payloads.

The server implements the **MCP 2026-07-28** specification (stateless core)
on the Python `mcp` 2.x SDK. It speaks `stdio` for local clients such as
Claude Code, Claude Desktop, Codex CLI and OpenCode, and stateless Streamable
HTTP at `/mcp` when hosted. It is developed by
[idss-mesa](https://github.com/idss-mesa){target=_blank} at the University of
New Mexico and released under the MIT license.

## Install in one minute

```bash
uv tool install git+https://github.com/idss-mesa/neon-mcp
claude mcp add neon -s user -- neon-mcp --transport stdio
```

Then ask your agent to call `neon_ping`; a successful reply confirms the
server is running and can reach the NEON API.

!!! note "Data downloads need a NEON API token"

    Product, site, location, release, taxonomy and prototype-dataset
    discovery work anonymously. Since NEON Data API 0.11.0 (June 2026) the
    data-file, data-query and sample endpoints require an API token; see
    [NEON API token](getting-started/api-token.md) to obtain one and pass it
    to neon-mcp.

## Documentation

This site is an [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md){target=_blank}
knowledge bundle: every page carries YAML frontmatter with `type`,
provenance and lifecycle fields, and the whole corpus is available to agents
at [`llms.txt`](llms.txt) and [`llms-full.txt`](llms-full.txt).

* [Getting started](getting-started/index.md) - Install neon-mcp, connect an MCP client, add your NEON API token and tune the configuration.
* [Tools](tools/index.md) - The 20 tools by family, with the generated tool reference, worked examples, pitfalls and error codes.
* [MCP protocol](mcp/index.md) - How neon-mcp implements the MCP 2026-07-28 stateless core and its stdio and Streamable HTTP transports.
* [Deploy](deploy/index.md) - Run neon-mcp as a hosted, stateless HTTP service behind TLS, and the security model operators rely on.
* [Develop](develop/index.md) - Architecture, adding a tool, the hermetic test suite, and how to contribute and release.
* [About](about/index.md) - How agents should consume this site, how to cite NEON data, licenses, and the change log.

## Where to get help

* Bugs and feature requests: [GitHub issues](https://github.com/idss-mesa/neon-mcp/issues){target=_blank}.
* Questions about the data themselves: the [NEON Data Portal](https://data.neonscience.org/){target=_blank}
  and [NEON Data API documentation](https://data.neonscience.org/data-api/){target=_blank}.
