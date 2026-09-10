"""Confined, plan-before-transfer downloads (stdio only).

Every destination resolves (symlinks included) under the configured download
directory; basenames must match ``^[A-Za-z0-9._-]+$``; every URL and redirect
hop must be on the host allow-list; the whole plan is checked against the
per-call file and byte caps before a single byte moves; files stream to
``.part`` and are renamed only after an optional MD5 check.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from neon_mcp.config import DownloadsConfig
from neon_mcp.errors import ToolError
from neon_mcp.neon.client import host_allowed

if TYPE_CHECKING:
    from neon_mcp.context import UpstreamStats
    from neon_mcp.neon.auth import Token
    from neon_mcp.neon.client import NeonClient

BASENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
FileStatus = Literal["downloaded", "skipped", "failed"]

__all__ = ["DownloadManager", "DownloadPlan", "DownloadedFile", "PlannedFile", "host_allowed"]


@dataclass(frozen=True)
class PlannedFile:
    url: str
    name: str
    size: int | None
    md5: str | None
    rel_dir: PurePosixPath
    requires_token: bool = False


@dataclass
class DownloadPlan:
    files: list[PlannedFile]
    total_bytes: int
    dest_root: Path
    skipped_existing: list[PlannedFile] = field(default_factory=list)
    destinations: dict[str, Path] = field(default_factory=dict)


@dataclass
class DownloadedFile:
    path: str
    name: str
    size: int | None
    md5_verified: bool | None
    status: FileStatus
    error: str | None = None
    seconds: float = 0.0


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DownloadManager:
    def __init__(self, config: DownloadsConfig, client: NeonClient) -> None:
        self.config = config
        self.client = client

    @property
    def root(self) -> Path:
        return self.config.directory.expanduser().resolve()

    def clean_subdir(self, value: str | None) -> PurePosixPath:
        if not value:
            return PurePosixPath()
        if value.startswith(("/", "\\")) or "\\" in value or ":" in value:
            raise ToolError(
                "download_denied",
                "dest_subdir must be a relative path using '/'.",
                details={"destSubdir": value},
            )
        parts = [p for p in value.split("/") if p not in ("", ".")]
        if any(p == ".." or not SEGMENT_RE.match(p) for p in parts):
            raise ToolError(
                "download_denied",
                "dest_subdir may contain only letters, digits, '.', '_', '-' and '/'.",
                details={"destSubdir": value},
            )
        return PurePosixPath(*parts)

    def safe_dest(self, *parts: str) -> Path:
        """Resolve ``parts`` under the download root, refusing traversal and symlink escapes."""
        if not parts or not BASENAME_RE.match(parts[-1]):
            raise ToolError(
                "download_denied", f"Refusing an unsafe file name: {parts[-1] if parts else ''!r}."
            )
        for part in parts:
            if (
                part in ("", ".", "..")
                or part.startswith(("/", "\\"))
                or ".." in PurePosixPath(part).parts
            ):
                raise ToolError("download_denied", f"Refusing an unsafe path segment: {part!r}.")
        root = self.root
        candidate = root.joinpath(*parts)
        resolved = candidate.resolve()
        if resolved != candidate and not resolved.is_relative_to(root):
            raise ToolError("download_denied", "Destination escapes the download directory.")
        if not resolved.is_relative_to(root):
            raise ToolError("download_denied", "Destination escapes the download directory.")
        return resolved

    def plan(
        self,
        files: Sequence[PlannedFile],
        *,
        dest_subdir: str | None,
        if_exists: Literal["skip", "error"],
        max_bytes: int | None,
    ) -> DownloadPlan:
        cfg = self.config
        sub = self.clean_subdir(dest_subdir)
        byte_cap = min(max_bytes, cfg.max_bytes_per_call) if max_bytes else cfg.max_bytes_per_call
        unique: dict[str, PlannedFile] = {}
        for f in files:
            unique.setdefault(str(sub / f.rel_dir / f.name), f)
        planned = list(unique.values())
        for f in planned:
            if not host_allowed(f.url, cfg.allowed_hosts):
                raise ToolError(
                    "download_denied",
                    f"{f.name} is not hosted on an allowed download host.",
                    details={"allowedHosts": list(cfg.allowed_hosts)},
                )
            if f.size is not None and f.size > cfg.max_file_bytes:
                raise ToolError(
                    "download_limit_exceeded",
                    f"{f.name} is {f.size} bytes, above the per-file limit of {cfg.max_file_bytes}.",
                    details={"file": f.name, "size": f.size, "maxFileBytes": cfg.max_file_bytes},
                )
        to_fetch: list[PlannedFile] = []
        skipped: list[PlannedFile] = []
        existing: list[str] = []
        destinations: dict[str, Path] = {}
        for f in planned:
            dest = self.safe_dest(*sub.parts, *f.rel_dir.parts, f.name)
            destinations[f.name + "|" + str(f.rel_dir)] = dest
            if dest.exists():
                same = (
                    f.size is not None
                    and dest.stat().st_size == f.size
                    and (not f.md5 or not cfg.verify_checksums or _md5(dest) == f.md5.lower())
                )
                if if_exists == "error":
                    existing.append(str(dest))
                    continue
                if same:
                    skipped.append(f)
                    continue
            to_fetch.append(f)
        if existing:
            raise ToolError(
                "download_denied",
                f"{len(existing)} file(s) already exist and if_exists='error'.",
                details={"existing": existing[:20]},
            )
        total = sum(f.size or 0 for f in to_fetch)
        if len(to_fetch) > cfg.max_files_per_call or total > byte_cap:
            raise ToolError(
                "download_limit_exceeded",
                f"The plan has {len(to_fetch)} file(s) / {total} bytes; limits are {cfg.max_files_per_call} files "
                f"and {byte_cap} bytes per call.",
                details={
                    "files": len(to_fetch),
                    "bytes": total,
                    "maxFiles": cfg.max_files_per_call,
                    "maxBytes": byte_cap,
                },
                hint="Narrow sites/months, filter with kind/table/name_contains, or call again for the rest.",
            )
        return DownloadPlan(
            files=to_fetch,
            total_bytes=total,
            dest_root=self.root,
            skipped_existing=skipped,
            destinations=destinations,
        )

    async def execute(
        self, plan: DownloadPlan, *, token: Token | None, stats: UpstreamStats
    ) -> list[DownloadedFile]:
        out: list[DownloadedFile] = []
        for f in plan.skipped_existing:
            dest = plan.destinations[f.name + "|" + str(f.rel_dir)]
            out.append(
                DownloadedFile(
                    path=str(dest),
                    name=f.name,
                    size=f.size,
                    md5_verified=True if f.md5 else None,
                    status="skipped",
                )
            )
        for f in plan.files:
            dest = plan.destinations[f.name + "|" + str(f.rel_dir)]
            try:
                result = await self.client.stream_to_file(
                    f.url,
                    dest,
                    token=token if f.requires_token else None,
                    max_bytes=self.config.max_file_bytes,
                    expected_md5=f.md5 if self.config.verify_checksums else None,
                    stats=stats,
                    allowed_hosts=self.config.allowed_hosts,
                )
                out.append(
                    DownloadedFile(
                        path=str(dest),
                        name=f.name,
                        size=result.bytes,
                        md5_verified=result.md5_verified,
                        status="downloaded",
                        seconds=result.seconds,
                    )
                )
            except ToolError as exc:
                out.append(
                    DownloadedFile(
                        path=str(dest),
                        name=f.name,
                        size=f.size,
                        md5_verified=False if exc.code == "checksum_mismatch" else None,
                        status="failed",
                        error=f"{exc.code}: {exc.message}",
                    )
                )
        return out
