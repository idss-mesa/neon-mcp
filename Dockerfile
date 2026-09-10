# neon-mcp — stateless Streamable HTTP deployment image.
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra pdf

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 neon
COPY --from=build --chown=neon:neon /app /app
USER neon
ENV PATH="/app/.venv/bin:$PATH" \
    NEON_MCP_SERVER__TRANSPORT=http \
    NEON_MCP_SERVER__BIND_ADDRESS=0.0.0.0 \
    NEON_MCP_SERVER__BIND_PORT=8080 \
    NEON_MCP_SERVER__LOG_LEVEL=info
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"
CMD ["neon-mcp", "--transport", "http", "--bind-address", "0.0.0.0"]
