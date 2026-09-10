from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import pytest

from neon_mcp.config import CacheConfig, DownloadsConfig, NeonConfig
from neon_mcp.context import UpstreamStats
from neon_mcp.errors import ToolError
from neon_mcp.neon.cache import TTLCache
from neon_mcp.neon.client import NeonClient
from neon_mcp.neon.downloads import DownloadManager, PlannedFile
from neon_mcp.neon.ratelimit import RateLimiter
from tests.conftest import FakeSleep
from tests.fixture_router import FixtureRouter, Reply, Route

BLOB = b"neon,data\n" * 500
URL = "https://storage.googleapis.com/fixture/blob.csv"


@pytest.fixture
async def manager(tmp_path: Path, router: FixtureRouter, fake_sleep: FakeSleep) -> DownloadManager:
    cfg = NeonConfig()
    client = NeonClient(
        cfg,
        cache=TTLCache(CacheConfig()),
        limiter=RateLimiter(cfg.rate_limit, max_concurrency=2),
        send_token_on_public=False,
        transport=router.transport,
        sleep=fake_sleep,
    )
    mgr = DownloadManager(DownloadsConfig(directory=tmp_path / "dl"), client)
    yield mgr  # type: ignore[misc]
    await client.aclose()


def planned(
    name: str = "blob.csv", size: int | None = len(BLOB), md5: str | None = None, url: str = URL
) -> PlannedFile:
    return PlannedFile(
        url=url,
        name=name,
        size=size,
        md5=md5 or hashlib.md5(BLOB).hexdigest(),  # noqa: S324
        rel_dir=PurePosixPath("DP1.00001.001", "ABBY", "2023-01"),
    )


def test_safe_dest_confinement(manager: DownloadManager, tmp_path: Path) -> None:
    ok = manager.safe_dest("DP1.00001.001", "ABBY", "a.csv")
    assert ok.is_relative_to(manager.root)
    for parts in (("..", "x.csv"), ("/etc", "passwd"), ("a", "b c.csv"), ("a", "..")):
        with pytest.raises(ToolError) as exc:
            manager.safe_dest(*parts)
        assert exc.value.code == "download_denied"
    outside = tmp_path / "outside"
    outside.mkdir()
    manager.root.mkdir(parents=True, exist_ok=True)
    (manager.root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ToolError, match="escapes"):
        manager.safe_dest("link", "f.csv")


def test_clean_subdir(manager: DownloadManager) -> None:
    assert manager.clean_subdir("project1/run_2") == PurePosixPath("project1/run_2")
    assert manager.clean_subdir(None) == PurePosixPath()
    for bad in ("../x", "/abs", "a\\b", "c:/x", "a/../b", "sp ace"):
        with pytest.raises(ToolError):
            manager.clean_subdir(bad)


def test_plan_caps_hosts_and_existing(manager: DownloadManager) -> None:
    files = [planned(f"f{i}.csv") for i in range(3)]
    manager.config.max_files_per_call = 2
    with pytest.raises(ToolError) as many:
        manager.plan(files, dest_subdir=None, if_exists="skip", max_bytes=None)
    assert many.value.code == "download_limit_exceeded" and many.value.details["files"] == 3
    manager.config.max_files_per_call = 50
    with pytest.raises(ToolError, match="bytes"):
        manager.plan(files, dest_subdir=None, if_exists="skip", max_bytes=len(BLOB) + 1)
    manager.config.max_file_bytes = 10
    with pytest.raises(ToolError, match="per-file"):
        manager.plan(files[:1], dest_subdir=None, if_exists="skip", max_bytes=None)
    manager.config.max_file_bytes = 1024**3
    with pytest.raises(ToolError, match="allowed download host"):
        manager.plan(
            [planned(url="https://evil.example/x.csv")],
            dest_subdir=None,
            if_exists="skip",
            max_bytes=None,
        )
    plan = manager.plan(files + files[:1], dest_subdir="proj", if_exists="skip", max_bytes=None)
    assert len(plan.files) == 3 and plan.total_bytes == 3 * len(BLOB)


async def test_execute_skip_and_mismatch(manager: DownloadManager, router: FixtureRouter) -> None:
    router.add(Route("GET", URL, Reply(content=BLOB, content_type="text/csv")))
    stats = UpstreamStats()
    plan = manager.plan([planned()], dest_subdir=None, if_exists="skip", max_bytes=None)
    first = await manager.execute(plan, token=None, stats=stats)
    assert first[0].status == "downloaded" and first[0].md5_verified is True
    dest = Path(first[0].path)
    assert dest.read_bytes() == BLOB and dest.parent.name == "2023-01"
    again = manager.plan([planned()], dest_subdir=None, if_exists="skip", max_bytes=None)
    assert again.files == [] and len(again.skipped_existing) == 1
    assert (await manager.execute(again, token=None, stats=stats))[0].status == "skipped"
    with pytest.raises(ToolError) as exists:
        manager.plan([planned()], dest_subdir=None, if_exists="error", max_bytes=None)
    assert exists.value.code == "download_denied"
    bad = manager.plan(
        [planned(name="other.csv", md5="f" * 32)],
        dest_subdir=None,
        if_exists="skip",
        max_bytes=None,
    )
    result = (await manager.execute(bad, token=None, stats=stats))[0]
    assert result.status == "failed" and "checksum_mismatch" in (result.error or "")
    assert not list(manager.root.rglob("other.csv*"))
