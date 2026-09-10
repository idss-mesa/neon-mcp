"""``neon-mcp`` command line.

Flags > environment (``NEON_MCP_*``, plus ``NEON_TOKEN``) > YAML (``--config``)
> defaults. There is deliberately no ``--token`` flag: tokens on a command
line leak into ``ps`` output and shell history.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from neon_mcp import __version__

if TYPE_CHECKING:
    from neon_mcp.config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neon-mcp",
        description="MCP (2026-07-28) server for the NEON Data API. Bare `neon-mcp` serves stdio.",
    )
    parser.add_argument("--config", type=Path, default=None, help="YAML config file.")
    parser.add_argument(
        "--transport", choices=("stdio", "http"), default=None, help="Transport (default stdio)."
    )
    parser.add_argument(
        "--bind-address", default=None, help="HTTP bind address (default 127.0.0.1)."
    )
    parser.add_argument(
        "--bind-port", type=int, default=None, help="HTTP bind port (default 8080)."
    )
    parser.add_argument(
        "--log-level", choices=("debug", "info", "warning", "error", "critical"), default=None
    )
    parser.add_argument(
        "--download-dir", type=Path, default=None, help="Directory downloads are confined to."
    )
    parser.add_argument("--no-downloads", action="store_true", help="Disable neon_download_files.")
    parser.add_argument(
        "--prewarm",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Build the product/site catalogs at startup (default: on for http).",
    )
    parser.add_argument(
        "--print-config", action="store_true", help="Print the effective config (token redacted)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Load config, call neon_ping(check_api=true) in-process, print JSON, exit 0/1.",
    )
    parser.add_argument("--version", action="version", version=f"neon-mcp {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from neon_mcp.config import load_config, set_active_config
    from neon_mcp.logging import setup_logging

    overrides = {
        "transport": args.transport,
        "bind_address": args.bind_address,
        "bind_port": args.bind_port,
        "log_level": args.log_level,
        "download_dir": str(args.download_dir) if args.download_dir else None,
        "downloads_enabled": False if args.no_downloads else None,
        "prewarm": args.prewarm,
    }
    config = load_config(args.config, flag_overrides=overrides)
    set_active_config(config)

    if args.print_config:
        import yaml

        yaml.safe_dump(config.model_dump_redacted(), sys.stdout, sort_keys=False)
        return 0

    setup_logging(config.server.log_level, transport=config.server.transport)
    if args.check:
        import asyncio

        return asyncio.run(_check(config))

    from neon_mcp.server import run

    run(config, transport=config.server.transport)
    return 0


async def _check(config: Config) -> int:
    import json

    from neon_mcp.server import create_server

    server = create_server(config, transport=config.server.transport)
    try:
        outcome = await server.call("neon_ping", {"check_api": True})
    finally:
        await server.aclose()
    payload = outcome.payload
    api = payload.get("api") or {}
    ok = not outcome.is_error and bool(api.get("reachable")) and api.get("status") == 200
    print(
        json.dumps(
            {
                "ok": ok,
                "version": __version__,
                "tokenConfigured": payload.get("tokenConfigured"),
                "apiReachable": bool(api.get("reachable")),
                "rateLimit": payload.get("rateLimit"),
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
