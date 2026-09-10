"""File listings from ``GET /data/{p}/{s}/{m}`` and ``POST /data/query``, normalised to one shape."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import Field

from neon_mcp.models.common import FileKind, NeonOutput, Page, ToolResultBase, Window
from neon_mcp.neon.filenames import parse_neon_filename
from neon_mcp.projections.common import null_list

PROVISIONAL = "PROVISIONAL"


class FileRecord(NeonOutput):
    site_code: str
    month: str
    release: str | None = None
    name: str
    kind: FileKind
    table: str | None = None
    hor: str | None = None
    ver: str | None = None
    tmi: str | None = None
    size: int | None = None
    md5: str | None = None
    crc32c: str | None = None
    url: str | None = None


class SiteMonthRow(NeonOutput):
    site_code: str
    month: str
    release: str | None = None
    package_type: str | None = None
    generation_date: str | None = None
    file_count: int
    total_bytes: int


class PackageLink(NeonOutput):
    type: str
    url: str
    requires_token_header: bool = True


class ExternalData(NeonOutput):
    name: str | None = None
    type: str | None = None
    url: str | None = None


class ReleaseFiles(NeonOutput):
    release: str
    generation_date: str | None = None
    site_months: int
    file_count: int
    total_bytes: int


class FileSummary(NeonOutput):
    site_months_requested: int
    site_months_with_data: int
    provisional_site_months: int
    file_count: int
    total_bytes: int
    releases: list[ReleaseFiles] = Field(default_factory=list)


class FileListing(ToolResultBase):
    budget_list: ClassVar[str | None] = "files"
    budget_elide_fields: ClassVar[tuple[str, ...]] = ("url",)
    budget_elide_flag: ClassVar[str | None] = "urls_elided"

    product_code: str
    package: str
    release: str | None = None
    include_provisional: bool
    site_codes: list[str]
    window: Window
    detail: Literal["files", "site_months", "summary"]
    summary: FileSummary
    site_months: list[SiteMonthRow] | None = None
    files: list[FileRecord] | None = None
    packages: list[PackageLink] = Field(default_factory=list)
    external_data: list[ExternalData] = Field(default_factory=list)
    url_expires_at: str | None = None
    urls_elided: bool = False
    curl_hint: str | None = None
    page: Page | None = None


class DownloadedFileOut(NeonOutput):
    path: str
    name: str
    size: int | None = None
    md5_verified: bool | None = None
    status: Literal["downloaded", "skipped", "failed"]
    error: str | None = None


class DownloadTotals(NeonOutput):
    files: int
    bytes: int
    seconds: float


class DownloadReport(ToolResultBase):
    download_dir: str
    requested: int
    files: list[DownloadedFileOut]
    totals: DownloadTotals


@dataclass
class Normalized:
    files: list[FileRecord]
    site_months: list[SiteMonthRow]
    packages: list[PackageLink]
    external: list[ExternalData]


def _record(raw: Mapping[str, Any], *, site: str, month: str, release: str | None) -> FileRecord:
    name = str(raw.get("name") or raw.get("fileName") or "")
    parsed = parse_neon_filename(name)
    return FileRecord(
        site_code=site,
        month=month,
        release=release,
        name=name,
        kind=parsed.kind,
        table=parsed.table,
        hor=parsed.hor,
        ver=parsed.ver,
        tmi=parsed.tmi,
        size=raw.get("size"),
        md5=raw.get("md5"),
        crc32c=raw.get("crc32c"),
        url=raw.get("url"),
    )


def _row(
    files: Sequence[FileRecord],
    *,
    site: str,
    month: str,
    release: str | None,
    package: str | None,
    generated: str | None,
) -> SiteMonthRow:
    return SiteMonthRow(
        site_code=site,
        month=month,
        release=release,
        package_type=package,
        generation_date=generated,
        file_count=len(files),
        total_bytes=sum(f.size or 0 for f in files),
    )


def normalize_single(raw: Mapping[str, Any], *, package: str) -> Normalized:
    site, month, release = str(raw.get("siteCode")), str(raw.get("month")), raw.get("release")
    files = [
        _record(f, site=site, month=month, release=release) for f in null_list(raw.get("files"))
    ]
    return Normalized(
        files=files,
        site_months=[
            _row(files, site=site, month=month, release=release, package=package, generated=None)
        ]
        if files
        else [],
        packages=[
            PackageLink(type=str(p.get("type")), url=str(p.get("url")))
            for p in null_list(raw.get("packages"))
            if p.get("url")
        ],
        external=[
            ExternalData(name=e.get("name"), type=e.get("type"), url=e.get("url"))
            for e in null_list(raw.get("externalData"))
        ],
    )


def normalize_query(raw: Mapping[str, Any]) -> Normalized:
    files: list[FileRecord] = []
    rows: list[SiteMonthRow] = []
    for rel in null_list(raw.get("releases")):
        tag = rel.get("release")
        for pkg in null_list(rel.get("packages")):
            site, month = str(pkg.get("siteCode")), str(pkg.get("month"))
            recs = [
                _record(f, site=site, month=month, release=tag) for f in null_list(pkg.get("files"))
            ]
            files.extend(recs)
            rows.append(
                _row(
                    recs,
                    site=site,
                    month=month,
                    release=tag,
                    package=pkg.get("packageType"),
                    generated=pkg.get("generationDate"),
                )
            )
    return Normalized(files=files, site_months=rows, packages=[], external=[])


def sort_files(files: Sequence[FileRecord]) -> list[FileRecord]:
    ordered = sorted(files, key=lambda f: (f.site_code, f.month, f.name))
    return sorted(ordered, key=lambda f: f.release or "", reverse=True)


def summarize(
    rows: Sequence[SiteMonthRow], *, requested: int, generated: Mapping[str, str | None]
) -> FileSummary:
    per: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        tag = row.release or "unknown"
        sm, fc, tb = per.get(tag, (0, 0, 0))
        per[tag] = (sm + 1, fc + row.file_count, tb + row.total_bytes)
    return FileSummary(
        site_months_requested=requested,
        site_months_with_data=len({(r.site_code, r.month) for r in rows}),
        provisional_site_months=sum(1 for r in rows if r.release == PROVISIONAL),
        file_count=sum(r.file_count for r in rows),
        total_bytes=sum(r.total_bytes for r in rows),
        releases=[
            ReleaseFiles(
                release=tag,
                generation_date=generated.get(tag),
                site_months=sm,
                file_count=fc,
                total_bytes=tb,
            )
            for tag, (sm, fc, tb) in sorted(per.items(), reverse=True)
        ],
    )
