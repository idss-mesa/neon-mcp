"""``/healthz`` (liveness) and ``/readyz`` (catalog warmth) for HTTP deployments."""

from __future__ import annotations

from typing import Any

from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.requests import Request
from starlette.responses import JSONResponse

from neon_mcp import __version__


async def healthz(request: Request) -> JSONResponse:
    """Always 200 while the process serves; inspects nothing upstream."""
    del request
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "transport": "http",
        }
    )


async def readyz(request: Request) -> JSONResponse:
    """503 while the catalog prewarm runs; 200 (``degraded`` flagged) afterwards."""
    server: Any = getattr(request.app.state, "neon_server", None)
    if server is None:  # pragma: no cover - misconfigured mount
        return JSONResponse({"status": "unknown"}, status_code=503)
    warmth = server.catalog.warmth()
    if server.readiness == "warming":
        return JSONResponse({"status": "warming"}, status_code=503)
    return JSONResponse(
        {
            "status": "ready",
            "catalog": {"products": warmth.products, "sites": warmth.sites},
            "degraded": server.readiness == "degraded",
            "tokenConfigured": server.config.token_value() is not None,
        }
    )
