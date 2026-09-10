---
title: "Resources and prompts"
description: "The neon:// guide and reference resources, the three resource templates backed by tools, and the three task prompts neon-mcp exposes."
type: Reference
tags:
  - tools
  - resources
  - prompts
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: resources-module
    resource: "https://github.com/idss-mesa/neon-mcp/blob/main/src/neon_mcp/resources.py"
    title: "neon-mcp resources (resources.py)"
    author: "team:idss-mesa"
  - id: mcp-spec
    resource: "https://modelcontextprotocol.io/specification/2026-07-28"
    title: "Model Context Protocol specification, 2026-07-28"
    author: "team:modelcontextprotocol"
status: stable
---

# Resources and prompts

## Resources

Static guides are cached by clients for 24 hours, derived references for one hour
(`ttlMs` on each read; `cacheScope` is always `public`)[^mcp-spec].

| URI | Kind | Content |
| --- | --- | --- |
| `neon://guide/agent-workflow` | static | The five-call recipe (search → availability → files → download → cite), input rules, error remedies |
| `neon://guide/api-token` | static | Which endpoints need a token, how to set it, rate limits |
| `neon://guide/citing-neon-data` | static | Data policy and the citation templates `neon_get_citation` renders |
| `neon://guide/product-code-anatomy` | static | Product codes, packages, the file-name grammar, releases and PROVISIONAL |
| `neon://reference/vocabularies` | static | Valid filter values: themes, teams, domains, taxon types, location types, releases, file kinds |
| `neon://reference/graphql-schema` | static | Root fields, inputs and object fields for `neon_graphql` |
| `neon://reference/sites` | derived | All 81 field sites with codes, names, domains, states and coordinates |
| `neon://reference/releases` | derived | Every release with its date and product count, plus the latest tag |

## Resource templates

| Template | Reads as |
| --- | --- |
| `neon://products/{productCode}` | the `neon_get_product` result |
| `neon://sites/{siteCode}` | the `neon_get_site` result (with products) |
| `neon://releases/{release}` | the `neon_get_release` result |

An unknown URI is a JSON-RPC `-32602` error with `data.code = "not_found"` and
`data.didYouMean`.

## Prompts

| Prompt | Arguments | Steers the agent to |
| --- | --- | --- |
| `neon_find_data` | `question` (required), `region`, `timeframe`, `organism_or_variable` | search products and sites, check availability, size the data (with a token) and cite |
| `neon_cite_dataset` | `product` (required), `release`, `site_codes` | produce citation text and BibTeX, with the provisional caveat when needed |
| `neon_plan_download` | `product`, `sites`, `start_month` (required), `end_month`, `package` | check the token, availability and size, then download (stdio) or hand back URLs, and cite |

[^mcp-spec]: Model Context Protocol specification, 2026-07-28. <https://modelcontextprotocol.io/specification/2026-07-28>
