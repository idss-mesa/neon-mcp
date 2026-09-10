from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from neon_mcp.config import Config, get_active_config, load_config, set_active_config


def test_defaults_and_effective_values() -> None:
    cfg = load_config(env={})
    assert cfg.server.transport == "stdio"
    assert cfg.neon.api_token is None
    assert cfg.limits.max_result_bytes == 50_000
    assert cfg.effective_downloads_enabled("stdio") and not cfg.effective_downloads_enabled("http")
    assert cfg.effective_prewarm("http") and not cfg.effective_prewarm("stdio")
    assert cfg.effective_token_for_public("stdio") and not cfg.effective_token_for_public("http")


def test_precedence_flag_over_env_over_yaml(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "server:\n  bind_port: 9000\n  log_level: debug\nlimits:\n  max_result_bytes: 30000\n"
    )
    cfg = load_config(
        path, env={"NEON_MCP_SERVER__BIND_PORT": "9100"}, flag_overrides={"log_level": "error"}
    )
    assert cfg.server.bind_port == 9100
    assert cfg.server.log_level == "error"
    assert cfg.limits.max_result_bytes == 30_000


def test_env_nesting_lists_and_nulls() -> None:
    cfg = load_config(
        env={
            "NEON_MCP_NEON__RATE_LIMIT__ANONYMOUS_RPS": "1.5",
            "NEON_MCP_CACHE__TTL_S__CATALOG": "60",
            "NEON_MCP_SERVER__ALLOWED_HOSTS": "a.example, b.example",
            "NEON_MCP_DOWNLOADS__ENABLED": "false",
            "NEON_MCP_NEON__TOKEN_FOR_PUBLIC_ENDPOINTS": "none",
        }
    )
    assert cfg.neon.rate_limit.anonymous_rps == 1.5
    assert cfg.cache.ttl_s.catalog == 60
    assert cfg.server.allowed_hosts == ["a.example", "b.example"]
    assert cfg.downloads.enabled is False
    assert cfg.neon.token_for_public_endpoints is None
    assert not cfg.effective_downloads_enabled("stdio")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"NEON_TOKEN": "tok-aaaa"}, "tok-aaaa"),
        ({"NEON_API_TOKEN": "tok-bbbb"}, "tok-bbbb"),
        ({"NEON_TOKEN": "tok-aaaa", "NEON_API_TOKEN": "tok-bbbb"}, "tok-aaaa"),
        ({"NEON_MCP_NEON__API_TOKEN": "tok-cccc", "NEON_TOKEN": "tok-aaaa"}, "tok-cccc"),
        ({"NEON_MCP_NEON__API_TOKEN": "   "}, None),
        ({}, None),
    ],
)
def test_token_env_fallbacks(env: dict[str, str], expected: str | None) -> None:
    assert load_config(env=env).token_value() == expected


def test_yaml_token_beats_fallback_env(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("neon:\n  api_token: yaml-token-1234\n")
    assert (
        load_config(path, env={"NEON_TOKEN": "env-token-1234"}).token_value() == "yaml-token-1234"
    )


def test_token_never_rendered() -> None:
    cfg = load_config(env={"NEON_TOKEN": "secret-token-value"})
    assert "secret-token-value" not in repr(cfg)
    dumped = cfg.model_dump_redacted()
    assert dumped["neon"]["api_token"] == "***"
    assert "secret-token-value" not in str(dumped)


def test_unknown_keys_warn(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("neon:\n  bogus: 1\nnope: {}\ncache:\n  ttl_s:\n    nada: 5\n")
    with caplog.at_level(logging.WARNING, logger="neon_mcp.config"):
        load_config(path, env={"NEON_MCP_SERVER__NOPE": "1"})
    text = caplog.text
    for key in ("neon.bogus", "'nope'", "cache.ttl_s.nada", "server.nope"):
        assert key in text


def test_download_dir_is_expanded() -> None:
    cfg = load_config(env={}, flag_overrides={"download_dir": "~/neon-x"})
    assert cfg.downloads.directory.is_absolute()
    assert "~" not in str(cfg.downloads.directory)
    assert load_config(env={}).downloads.directory.is_absolute()


def test_invalid_values_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_config(env={"NEON_MCP_SERVER__TRANSPORT": "sse"})
    path = tmp_path / "c.yaml"
    path.write_text("- not\n- a mapping\n")
    with pytest.raises(ValueError, match="mapping"):
        load_config(path, env={})
    with pytest.raises(KeyError):
        load_config(env={}, flag_overrides={"token": "x"})


def test_active_config_roundtrip() -> None:
    cfg = Config()
    set_active_config(cfg)
    try:
        assert get_active_config() is cfg
    finally:
        set_active_config(None)
    assert isinstance(get_active_config(), Config)
