---
title: "Utilities and errors"
description: "neon_ping for status and connectivity, neon_get_document for NEON documents, and the error codes every neon-mcp tool can return with their remedies."
type: Reference
tags:
  - tools
  - errors
  - documents
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: errors-module
    resource: "https://github.com/idss-mesa/neon-mcp/blob/main/src/neon_mcp/errors.py"
    title: "neon-mcp error model (errors.py)"
    author: "team:idss-mesa"
status: stable
---

# Utilities and errors

## neon_ping

[`neon_ping`](reference.md#neon_ping) reports the version, protocol, transport,
whether a token is available (never the token), whether downloads are enabled,
catalog warmth, cache statistics and rate-limit headroom. It makes no request unless
`check_api=true`, which sends one ~1 KB taxonomy request. `neon-mcp --check` runs the
same check from the command line.

## neon_get_document

[`neon_get_document`](reference.md#neon_get_document) returns a NEON document's
metadata (type, size, file name, description, the products that reference it) by
spec number (`NEON.DOC.000780vD`) or documents URL. `extract_text=true` downloads it
into memory (up to 25 MiB), extracts PDF text with pypdf (install
`neon-mcp[pdf]`), and pages it with `char_offset` / `max_chars`; `pages` selects PDF
pages. Nothing is written to disk.

## Error codes

A failed call returns `isError: true` with
`structuredContent = {"error": {"code", "message", "details", "hint"}}`. Codes are stable:

| Code | Meaning | Remedy |
| --- | --- | --- |
| `invalid_argument` | An argument is missing, malformed, unknown or conflicts with another; also NEON 400s that are not "not found" | Read the message: it names the field (and lists valid ones for unknown fields) |
| `not_found` | Unknown code, name or file (NEON answers 400 "… not found") | Use `details.didYouMean` or `details.validReleases` |
| `ambiguous_input` | A name matched several codes | Retry with a code from `details.candidates` |
| `auth_required` | The endpoint needs a NEON API token and none is available | [NEON API token](../getting-started/api-token.md) |
| `forbidden` | NEON rejected the token | Create a new token |
| `rate_limited` | NEON's rate limit is exhausted | Wait `details.retryAfterSeconds`; a token raises the limit |
| `upstream_error` | NEON failed (5xx) or returned something unexpected | Retry later |
| `upstream_unavailable` | NEON unreachable or timed out | Retry; `neon_ping(check_api=true)` |
| `graphql_error` | NEON rejected a GraphQL query | Check field names in `neon://reference/graphql-schema` |
| `query_too_large` | More than 500 site-months, or too many locations for proximity | Narrow sites, months or types |
| `download_limit_exceeded` | A download plan exceeds the file or byte caps | Narrow the selectors or call again for the rest |
| `download_denied` | Unsafe destination, disallowed host, or existing files with `if_exists="error"` | Fix the path or options |
| `checksum_mismatch` | A downloaded file's MD5 differed (the partial file was removed) | Retry the download |
| `result_too_large` | A result stays above 200 KB after trimming, or a document is too large to read | Narrow the request |
| `feature_unavailable` | Downloads disabled, or pypdf missing | Enable the feature or install the extra |
| `not_available_in_http_mode` | Downloads were requested over HTTP | Use the signed URLs from `neon_list_files` |
| `catalog_unavailable` | The product or site catalog could not be built | Retry later |
| `unknown_tool` | No tool by that name | See `tools/list` |
| `internal_error` | A bug; `details.correlationId` matches the server log | Report it with the correlation id |
