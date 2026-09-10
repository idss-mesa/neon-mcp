from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import structlog

from neon_mcp.logging import redact_secrets, register_secret, registered_secrets, setup_logging

TOKEN = "unit-test-token-DO-NOT-LOG"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield
    setup_logging("warning", "stdio")


def test_credential_keys_masked_flags_kept() -> None:
    event = redact_secrets(
        None,
        "info",
        {
            "event": "x",
            "api_token": "abc",
            "authorization": "Bearer z",
            "token_configured": True,
            "n": 1,
        },
    )
    assert event["api_token"] == "***"
    assert event["authorization"] == "***"
    assert event["token_configured"] is True
    assert event["n"] == 1


def test_registered_secret_masked_anywhere() -> None:
    register_secret(TOKEN)
    event = redact_secrets(
        None, "info", {"event": f"GET https://x?t={TOKEN}", "nested": {"h": [TOKEN], "ok": "fine"}}
    )
    assert TOKEN not in json.dumps(event)
    assert event["nested"]["ok"] == "fine"


def test_short_values_are_not_registered() -> None:
    register_secret("abc")
    register_secret(None)
    assert "abc" not in registered_secrets()


def test_stdio_logs_go_to_stderr_only(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("info", "stdio")
    register_secret(TOKEN)
    structlog.get_logger("t").info("hello", api_token="leak-me", url=f"x?{TOKEN}")
    out, err = capsys.readouterr()
    assert out == ""
    assert "hello" in err
    assert "leak-me" not in err
    assert TOKEN not in err


def test_http_logs_are_json(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("info", "http")
    structlog.get_logger("t").info("evt", request_id="r1")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "evt"
    assert record["request_id"] == "r1"
