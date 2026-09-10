---
title: "Samples"
description: "Look up NEON sample classes and trace a physical sample's custody chain; neon_get_sample is the one tool that may ask the user a question (MRTR)."
type: Guide
tags:
  - tools
  - samples
  - MRTR
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: neon-samples
    resource: "https://data.neonscience.org/data-api/endpoints/samples/"
    title: "NEON Data API — Samples endpoint"
    author: "team:neon"
  - id: mcp-spec
    resource: "https://modelcontextprotocol.io/specification/2026-07-28"
    title: "Model Context Protocol specification, 2026-07-28"
    author: "team:modelcontextprotocol"
status: stable
stale_after: "2027-03-10T00:00:00Z"
---

# Samples

NEON tracks physical samples (beetle pinnings, soil cores, DNA extracts, …) from
collection through subsampling and archiving[^neon-samples]. Tools:
[`neon_list_sample_classes`](reference.md#neon_list_sample_classes) (no token) and
[`neon_get_sample`](reference.md#neon_get_sample) (token).

## Sample classes

A **sample class** such as `bet_IDandpinning_in.individualID` names the NEON table
and field an identifier comes from. `neon_list_sample_classes` lists all supported
classes with descriptions (filter with `query`), or the classes one `sample_tag`
belongs to. A tag with no classes returns an empty list, not an error.

## One sample

Identify a sample by exactly one of `sample_tag` (+ `sample_class`), `sample_uuid`,
`barcode` or `archive_guid`. The result lists its custody events (each event's field
entries folded into an object; keep only some with `fields`), and its parent and child
samples. `degree=N` (1–5) also returns relatives up to N steps away.

## Asking which class (MRTR)

A sample tag can belong to several classes. When you pass a tag without a class:

* if the client supports elicitation, neon-mcp returns an MCP **input_required**
  result asking the user to pick one of the candidate classes; the client retries
  with the answer and neon-mcp re-checks that it is still a valid class for the
  tag[^mcp-spec];
* otherwise the call fails with `ambiguous_input` and lists the candidates.

The continuation (`requestState`) holds only the question — never the token.

[^neon-samples]: NEON Data API — Samples endpoint. <https://data.neonscience.org/data-api/endpoints/samples/>
[^mcp-spec]: Model Context Protocol specification, 2026-07-28. <https://modelcontextprotocol.io/specification/2026-07-28>
