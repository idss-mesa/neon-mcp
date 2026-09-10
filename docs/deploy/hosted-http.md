---
title: "Hosted HTTP deployment"
description: "Run neon-mcp as a stateless Streamable HTTP service with uvicorn behind nginx or Caddy, systemd or Docker, health checks and horizontal scaling."
type: Guide
tags:
  - deploy
  - http
  - docker
  - systemd
generated:
  by: "claude/opus-5"
  at: "2026-09-10T00:00:00Z"
sources:
  - id: uvicorn
    resource: "https://www.uvicorn.org/deployment/"
    title: "Uvicorn — Deployment"
    author: "team:encode"
  - id: caddy
    resource: "https://caddyserver.com/docs/caddyfile/directives/reverse_proxy"
    title: "Caddy — reverse_proxy"
    author: "team:caddy"
status: stable
---

# Hosted HTTP deployment

A hosted neon-mcp lets many users connect with
`claude mcp add --transport http neon https://neon-mcp.example.org/mcp`. The
server is stateless, so any number of instances can sit behind a plain load
balancer.

## Configuration essentials

```bash
NEON_MCP_SERVER__TRANSPORT=http
NEON_MCP_SERVER__BIND_ADDRESS=127.0.0.1        # the proxy connects locally
NEON_MCP_SERVER__BIND_PORT=8080
NEON_MCP_SERVER__PUBLIC_BASE_URL=https://neon-mcp.example.org   # enables per-request tokens, sets host allow-list
```

Users bring their own NEON token in `X-API-Token`; see [Security](security.md) before
configuring an operator token.

## Behind a reverse proxy

Terminate TLS at the proxy (the token is a bearer secret), forward `Host` unchanged,
and pass `X-API-Token` through. Caddy[^caddy]:

```text
neon-mcp.example.org {
    reverse_proxy 127.0.0.1:8080
}
```

nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_buffering off;          # single SSE frame per response
}
```

## systemd

```ini
[Unit]
Description=neon-mcp (Streamable HTTP)
After=network-online.target

[Service]
User=neon
EnvironmentFile=/etc/neon-mcp.env
ExecStart=/opt/neon-mcp/.venv/bin/neon-mcp --transport http
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
```

## Docker

The repository ships a `Dockerfile` (Python 3.13 slim, non-root user, `HEALTHCHECK`
on `/healthz`) and `docker-compose.yml`:

```bash
docker build -t neon-mcp .
docker run -p 127.0.0.1:8080:8080 -e NEON_MCP_SERVER__PUBLIC_BASE_URL=https://neon-mcp.example.org neon-mcp
```

## Health, readiness and scaling

* `/healthz` is liveness only. `/readyz` returns 503 while the product and site
  catalogs prewarm at startup (a few seconds), then 200; `degraded: true` means the
  prewarm failed and catalogs will build lazily.
* Each instance keeps its own in-memory cache (catalogs about 4 MB, one-hour TTL,
  refreshed in the background before expiry, served stale for up to 24 h if NEON is
  down). Allow roughly 300 MB of memory per instance, more if GraphQL falls back to the
  30 MB REST product list.
* Anonymous callers share the server's IP-based NEON quota (200 burst, 2 requests/s);
  callers with tokens use their own. For busy public deployments, require users to
  send tokens.

[^uvicorn]: Uvicorn — Deployment. <https://www.uvicorn.org/deployment/>
[^caddy]: Caddy — reverse_proxy. <https://caddyserver.com/docs/caddyfile/directives/reverse_proxy>
