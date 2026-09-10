---
title: "Security"
description: "How neon-mcp protects NEON tokens, confines downloads, validates hosts and limits requests, and what operators must configure."
type: Policy
tags:
  - deploy
  - security
  - tokens
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: mcp-security
    resource: "https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices"
    title: "MCP specification — Security best practices"
    author: "team:modelcontextprotocol"
status: stable
---

# Security

## NEON tokens

* A token is used only as the `X-API-Token` header to data.neonscience.org — never in a
  URL, never to a storage host (signed download URLs need no token).
* It never appears in logs (a redaction processor masks credential-like keys and every
  token the process has seen), results, error details, cache keys (a 12-character
  SHA-256 prefix identifies it instead), `/healthz`, `/readyz`, or MRTR
  `requestState`.
* There is no command-line flag for it (process lists and shell history would expose it).
* Over HTTP a per-request token is accepted only when `server.public_base_url` is
  `https://`, and the operator's own token is not lent to anonymous callers unless
  `server.share_config_token_over_http` is set — only do that on private deployments.

## Requests

* DNS-rebinding protection: loopback binds are protected automatically; public
  deployments get a `Host`/`Origin` allow-list from `public_base_url`,
  `allowed_hosts` and `allowed_origins`[^mcp-security].
* Request bodies are capped at 1 MiB; `GET`/`DELETE` on `/mcp` are refused (no idle
  streams); results are capped at 50 KB (trimmed) and 200 KB (hard).
* Every NEON call goes through a per-identity rate limiter kept 10 % under NEON's limits.
* `neon_graphql` accepts only read-only queries against allow-listed roots, bounded in
  length and depth.

## Downloads (stdio only)

* The download tool is not listed and refuses to run over HTTP.
* Destinations must resolve (following symlinks) inside `downloads.directory`; file
  names must match `^[A-Za-z0-9._-]+$`; `dest_subdir` must be relative without `..`.
* Every URL and redirect hop must be on `downloads.allowed_hosts`; the plan is refused
  before any transfer above 50 files / 2 GiB per call or 1 GiB per file.
* Files stream to `.part` and are renamed only after the MD5 check passes.

## Reporting

Report vulnerabilities privately through GitHub's security advisories for
[idss-mesa/neon-mcp](https://github.com/idss-mesa/neon-mcp/security){target=_blank}.

[^mcp-security]: MCP specification — Security best practices. <https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices>
