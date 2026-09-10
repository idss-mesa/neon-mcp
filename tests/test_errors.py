from __future__ import annotations

from typing import Any

import pytest

from neon_mcp.errors import InputRequired, NeonApiError, ToolError, map_api_error, redact


def err(status: int, detail: str = "x", **kw: Any) -> NeonApiError:
    return NeonApiError(status, detail, "/products/DP1.00001.001", **kw)


def test_403_without_token_is_auth_required() -> None:
    e = map_api_error(err(403, "Access Denied"), token_sent=False, requires_token=True)
    assert e.code == "auth_required"
    assert e.details == {
        "guide": "neon://guide/api-token",
        "endpoint": "/products/DP1.00001.001",
        "tokenSource": "none",
    }
    assert "myaccount" in e.message


def test_403_with_token_is_forbidden_and_default_uses_exception_flag() -> None:
    assert map_api_error(err(403), token_sent=True, requires_token=True).code == "forbidden"
    assert map_api_error(err(403, token_sent=True)).code == "forbidden"
    assert map_api_error(err(403, token_sent=False)).code == "auth_required"


def test_400_not_found_carries_valid_releases() -> None:
    e = map_api_error(
        err(
            400,
            "Release not found. See data response element",
            data={"validReleases": ["RELEASE-2025"]},
        ),
        entity="release",
        identifier="RELEASE-1999",
    )
    assert e.code == "not_found"
    assert e.details["validReleases"] == ["RELEASE-2025"]
    assert "release 'RELEASE-1999'" in e.message


@pytest.mark.parametrize(
    ("status", "detail", "code"),
    [
        (400, "Product code not found", "not_found"),
        (
            400,
            "Taxon type code and taxon rank parameters must not both be specified",
            "invalid_argument",
        ),
        (404, "No Sample Classes Found", "not_found"),
        (429, "API rate limit exceeded", "rate_limited"),
        (500, "boom", "upstream_error"),
        (502, "<html>", "upstream_error"),
        (418, "teapot", "upstream_error"),
    ],
)
def test_status_table(status: int, detail: str, code: str) -> None:
    assert map_api_error(err(status, detail)).code == code


def test_rate_limited_details() -> None:
    e = map_api_error(
        err(
            429,
            retry_after_s=2.0,
            headers={"X-RateLimit-Limit": "200", "x-ratelimit-remaining": "0"},
        )
    )
    assert e.details["retryAfterSeconds"] == 2.0
    assert e.details["limit"] == 200
    assert e.details["remaining"] == 0
    assert e.details["identity"] == "anonymous"


def test_transport_and_decode_kinds() -> None:
    assert (
        map_api_error(NeonApiError(0, "ConnectError", "/sites", kind="transport")).code
        == "upstream_unavailable"
    )
    decoded = map_api_error(
        NeonApiError(200, "not json", "/sites", kind="decode", content_type="text/html")
    )
    assert decoded.code == "upstream_error"
    assert decoded.details["contentType"] == "text/html"


def test_secrets_are_redacted_from_messages() -> None:
    e = map_api_error(err(400, "bad value s3cr3t-token-value here"), secrets=["s3cr3t-token-value"])
    assert "s3cr3t-token-value" not in e.message
    assert redact("a TOKEN b", ["TOKEN", ""]) == "a *** b"


def test_payload_shape() -> None:
    assert ToolError("not_found", "m", details={"a": 1}, hint="h").to_payload() == {
        "error": {"code": "not_found", "message": "m", "details": {"a": 1}, "hint": "h"}
    }
    assert "hint" not in ToolError("invalid_argument", "m").to_payload()["error"]


def test_input_required_copies_its_inputs() -> None:
    schema = {"type": "object"}
    state = {"field": "x"}
    pending = InputRequired(key="k", message="pick", requested_schema=schema, state=state)
    schema["x"] = 1
    state["y"] = 2
    assert pending.requested_schema == {"type": "object"}
    assert pending.state == {"field": "x"}
