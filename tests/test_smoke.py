from __future__ import annotations

import json
from importlib.metadata import entry_points
from typing import Any

import pytest

import neon_mcp
from neon_mcp import __main__ as cli
from tests.fixture_router import TEST_TOKEN, FixtureRouter, Reply, load_headers


def test_version_and_entry_point() -> None:
    assert neon_mcp.__version__ == "0.1.0"
    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts")}
    assert scripts.get("neon-mcp") == "neon_mcp.__main__:main"


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "neon-mcp 0.1.0" in capsys.readouterr().out


def test_print_config_redacts_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NEON_TOKEN", "cli-secret-token-1234")
    assert cli.main(["--print-config", "--transport", "http", "--no-downloads"]) == 0
    out = capsys.readouterr().out
    assert "cli-secret-token-1234" not in out
    assert "api_token: '***'" in out
    assert "transport: http" in out


def _patch_server(monkeypatch: pytest.MonkeyPatch, router: FixtureRouter) -> None:
    import neon_mcp.server as server_mod

    real = server_mod.create_server

    def fake(config: Any, **kw: Any) -> Any:
        kw["http_transport"] = router.transport
        return real(config, **kw)

    monkeypatch.setattr(server_mod, "create_server", fake)


def test_check_succeeds(
    monkeypatch: pytest.MonkeyPatch, router: FixtureRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NEON_TOKEN", raising=False)
    _patch_server(monkeypatch, router)
    assert cli.main(["--check", "--log-level", "error"]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (
        report["ok"] is True
        and report["apiReachable"] is True
        and report["tokenConfigured"] is False
        and report["tokenAccepted"] is None
        and report["apiStatus"] == 200
    )


def test_check_fails_when_neon_errors(
    monkeypatch: pytest.MonkeyPatch, router: FixtureRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_server(monkeypatch, router)
    router.inject_5xx(3)
    assert cli.main(["--check", "--log-level", "error"]) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["ok"] is False


def test_check_reports_a_rejected_token(
    monkeypatch: pytest.MonkeyPatch, router: FixtureRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NEON_MCP_NEON__API_TOKEN", raising=False)
    monkeypatch.setenv("NEON_TOKEN", TEST_TOKEN)
    _patch_server(monkeypatch, router)
    router.inject(
        Reply(fixture="data_403.json", status=403, headers=load_headers("example_403.headers"))
    )
    assert cli.main(["--check", "--log-level", "error"]) == 1
    out = capsys.readouterr().out
    report = json.loads(out.strip().splitlines()[-1])
    assert report["tokenConfigured"] is True and report["tokenAccepted"] is False
    assert report["apiStatus"] == 403 and "rejected the API token" in report["problem"]
    assert TEST_TOKEN not in out
