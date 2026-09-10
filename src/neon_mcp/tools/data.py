"""``neon_list_files`` and ``neon_download_files`` (data files; NEON API token required)."""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, model_validator

from neon_mcp.context import ToolContext
from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.models.common import (
    FileKind,
    Month,
    NeonInput,
    PackageType,
    ReleaseTag,
    Resolved,
    SpecNumber,
    Uuid,
    Window,
    end_month_field,
    start_month_field,
)
from neon_mcp.neon.auth import require_token
from neon_mcp.neon.downloads import DownloadManager, PlannedFile
from neon_mcp.neon.filenames import parse_neon_filename
from neon_mcp.neon.months import MonthRanges, months_between
from neon_mcp.neon.resolve import resolve_product, resolve_sites
from neon_mcp.projections.common import null_list, paginate, parse_gcs_expiry
from neon_mcp.projections.data import (
    PROVISIONAL,
    DownloadedFileOut,
    DownloadReport,
    DownloadTotals,
    FileListing,
    FileRecord,
    Normalized,
    normalize_query,
    normalize_single,
    sort_files,
    summarize,
)
from neon_mcp.registry import register_tool
from neon_mcp.tools._common import api_error, check_window, fmt_list, source


class _Selectors(NeonInput):
    product: str | None = Field(None, description="Product code or name.")
    site_codes: list[str] | None = Field(
        None, min_length=1, description="Site codes or names (up to 30)."
    )
    start_month: Month | None = start_month_field()
    end_month: Month | None = end_month_field()
    package: PackageType = Field("basic", description="basic (default) or expanded.")
    release: ReleaseTag | None = Field(
        None, description="Only files in this release (default: latest per month)."
    )
    include_provisional: bool = Field(True, description="Include PROVISIONAL (unreleased) months.")
    kind: FileKind | None = Field(
        None, description="data, variables, readme, sensor_positions, eml, ... or package."
    )
    table: str | None = Field(None, description="Table name, e.g. 2DWSD_30min or brd_countdata.")
    hor: str | None = Field(None, description="Horizontal index, e.g. 000.")
    ver: str | None = Field(None, description="Vertical index, e.g. 010.")
    tmi: str | None = Field(None, description="Temporal index in minutes, e.g. 030.")
    name_contains: str | None = Field(None, description="Substring the file name must contain.")


class ListFilesIn(_Selectors):
    product: str = Field(description="Product code or name.")
    site_codes: list[str] = Field(min_length=1, description="Site codes or names (up to 30).")
    start_month: Month = start_month_field("First month (YYYY-MM).", default=...)
    detail: Literal["files", "site_months", "summary"] = Field(
        "files",
        description="files (default), site_months (one row per site-month), summary (totals only).",
    )
    include_urls: bool = Field(
        True, description="Include signed URLs (valid ~7 days; they dominate result size)."
    )
    filename: str | None = Field(
        None, description="One exact NEON file name (single site and month): its URL."
    )
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


def _keep(f: FileRecord, args: _Selectors) -> bool:
    return (
        (args.kind is None or f.kind == args.kind)
        and (args.table is None or (f.table or "").lower() == args.table.lower())
        and (args.hor is None or f.hor == args.hor)
        and (args.ver is None or f.ver == args.ver)
        and (args.tmi is None or f.tmi == args.tmi)
        and (args.name_contains is None or args.name_contains.lower() in f.name.lower())
    )


async def _collect(
    args: _Selectors, ctx: ToolContext
) -> tuple[str, list[str], str, str, Normalized, list[Resolved], list[str]]:
    """Resolve selectors and fetch the listing (single cell GET or POST /data/query)."""
    assert args.product is not None and args.site_codes is not None and args.start_month is not None  # noqa: S101
    limits = ctx.config.limits
    code, res = await resolve_product(args.product, ctx)
    if len(args.site_codes) > limits.max_sites_per_call:
        raise ToolError("invalid_argument", f"At most {limits.max_sites_per_call} sites per call.")
    sites, resolved = await resolve_sites(args.site_codes, ctx)
    if res:
        resolved.insert(0, res)
    start = args.start_month
    end = args.end_month or start
    check_window(start, end)
    cells = len(sites) * months_between(start, end)
    if cells > limits.max_site_months_per_query:
        raise ToolError(
            "query_too_large",
            f"{len(sites)} site(s) x {months_between(start, end)} month(s) = {cells} site-months exceeds "
            f"{limits.max_site_months_per_query}.",
            details={"siteMonths": cells, "limit": limits.max_site_months_per_query},
            hint="Split by sites or years, or check neon_get_availability first.",
        )
    token = require_token(ctx, endpoint="GET /data")
    endpoints: list[str] = []
    try:
        if len(sites) == 1 and start == end:
            env = await ctx.client.get_json(
                f"/data/{code}/{sites[0]}/{start}",
                {"package": args.package, "release": args.release},
                token=token,
                stats=ctx.stats,
                cache="data",
            )
            data = normalize_single(env.data or {}, package=args.package)
            if not args.include_provisional:
                data.files = [f for f in data.files if f.release != PROVISIONAL]
                data.site_months = [r for r in data.site_months if r.release != PROVISIONAL]
            endpoints.append("single")
        else:
            body: dict[str, Any] = {
                "productCode": code,
                "siteCodes": sites,
                "startDateMonth": start,
                "endDateMonth": end,
                "package": args.package,
                "includeProvisional": args.include_provisional,
            }
            if args.release:
                body["release"] = args.release
            env = await ctx.client.post_json(
                "/data/query", body, token=token, stats=ctx.stats, cache="data"
            )
            data = normalize_query(env.data or {})
            endpoints.append("query")
    except NeonApiError as exc:
        if exc.status in (400, 404):
            raise api_error(
                exc,
                entity="data",
                identifier=f"{code} at {fmt_list(sites)} {start}..{end}",
                hint="Check months with neon_get_availability.",
            ) from None
        raise
    data.files = [f for f in data.files if _keep(f, args)]
    return code, sites, start, end, data, resolved, endpoints


@register_tool(
    "neon_list_files",
    title="List NEON data files",
    description=(
        "Data files for a product at sites over months (NEON API token required): names, kinds, tables, "
        "HOR/VER/TMI, sizes, MD5s and signed URLs (~7 days), plus package ZIP links for a single site-month. "
        "detail='summary' or 'site_months' sizes a pull without listing files. Next: call "
        "neon_download_files with the same selectors (stdio), or use the URLs."
    ),
    input_model=ListFilesIn,
    output_model=FileListing,
    surface="data",
    endpoints=[
        "GET /data/{productCode}/{siteCode}/{yearMonth}",
        "GET /data/{productCode}/{siteCode}/{yearMonth}/{filename}",
        "POST /data/query",
    ],
    requires_token=True,
)
async def neon_list_files(args: ListFilesIn, ctx: ToolContext) -> FileListing:
    notes: list[str] = []
    if args.filename is not None:
        parsed = parse_neon_filename(args.filename)
        if parsed.kind == "other" and not args.filename.startswith("NEON."):
            raise ToolError("invalid_argument", "filename must be an exact NEON file name.")
    code, sites, start, end, data, resolved, mode = await _collect(args, ctx)
    files = sort_files(data.files)

    if args.filename is not None:
        if len(sites) != 1 or start != end:
            raise ToolError("invalid_argument", "filename needs exactly one site and one month.")
        token = require_token(ctx, endpoint="GET /data")
        match = [f for f in files if f.name == args.filename]
        url = await ctx.client.resolve_redirect(
            f"/data/{code}/{sites[0]}/{start}/{args.filename}",
            {"package": args.package},
            token=token,
            stats=ctx.stats,
        )
        if url is not None:
            if match:
                match[0].url = url
            else:
                parsed = parse_neon_filename(args.filename)
                match = [
                    FileRecord(
                        site_code=sites[0],
                        month=start,
                        name=args.filename,
                        kind=parsed.kind,
                        table=parsed.table,
                        hor=parsed.hor,
                        ver=parsed.ver,
                        tmi=parsed.tmi,
                        url=url,
                    )
                ]
        if not match:
            raise ToolError(
                "not_found",
                f"{args.filename} is not in {code} {sites[0]} {start}.",
                details={"available": [f.name for f in files[:20]]},
            )
        files = match

    generated = {r.release or "unknown": r.generation_date for r in data.site_months}
    summary = summarize(
        data.site_months, requested=len(sites) * months_between(start, end), generated=generated
    )
    listing = FileListing(
        product_code=code,
        package=args.package,
        release=args.release,
        include_provisional=args.include_provisional,
        site_codes=sites,
        window=Window(start_month=start, end_month=end),
        detail=args.detail,
        summary=summary,
        packages=data.packages,
        external_data=data.external,
    )
    if args.detail == "files":
        page_files, page = paginate(files, offset=args.offset, limit=args.limit)
        if not args.include_urls:
            for f in page_files:
                f.url = None
        listing.files, listing.page = page_files, page
        first_url = next((f.url for f in page_files if f.url), None)
        listing.url_expires_at = parse_gcs_expiry(first_url)
    elif args.detail == "site_months":
        rows, page = paginate(
            sorted(data.site_months, key=lambda r: (r.site_code, r.month)),
            offset=args.offset,
            limit=args.limit,
        )
        listing.site_months, listing.page = rows, page
    if data.packages:
        pkg = data.packages[0]
        listing.curl_hint = (
            f'curl -L -H "X-API-Token: $NEON_TOKEN" -o {code}_{sites[0]}_{start}.zip "{pkg.url}"'
        )
    if summary.provisional_site_months:
        notes.append(
            f"{summary.provisional_site_months} site-month(s) are PROVISIONAL (unreleased; may change)."
        )
    if summary.site_months_with_data < summary.site_months_requested:
        notes.append(
            f"{summary.site_months_requested - summary.site_months_with_data} requested site-month(s) "
            "have no files; check neon_get_availability."
        )
    if listing.files and listing.url_expires_at:
        notes.append("Signed URLs expire at urlExpiresAt (about 7 days); list again to refresh.")
    steps: list[str] = []
    selector = (
        f"product='{code}', site_codes={fmt_list(sites)}, start_month='{start}', end_month='{end}'"
    )
    if ctx.config.effective_downloads_enabled(ctx.transport):
        steps.append(
            f"neon_download_files({selector}{', kind=' + repr(args.kind) if args.kind else ''})"
        )
    else:
        steps.append(
            "Downloads are stdio-only; fetch the signed URLs directly (no token needed for them)"
        )
    if listing.page and listing.page.next_offset is not None:
        steps.append(f"Repeat with offset={listing.page.next_offset} for more")
    steps.append(f"neon_get_citation(product='{code}')")
    listing.resolved, listing.notes, listing.next_steps = resolved, notes, steps
    listing.source = source(ctx, "rest")
    del mode
    return listing


class DownloadFilesIn(_Selectors):
    as_zip: bool = Field(
        False, description="Download NEON's package ZIP per site-month instead of files."
    )
    prototype_uuid: Uuid | None = Field(
        None, description="Download a prototype dataset's files instead."
    )
    file_names: list[str] | None = Field(
        None, description="With prototype_uuid: only these file names."
    )
    spec_number: SpecNumber | None = Field(
        None, description="Download one NEON document (e.g. NEON.DOC.000780vD)."
    )
    dest_subdir: str | None = Field(
        None, description="Relative sub-directory of the download directory."
    )
    if_exists: Literal["skip", "error"] = Field(
        "skip", description="skip identical existing files (default) or error."
    )
    max_bytes: int | None = Field(None, ge=1, description="Refuse the plan above this many bytes.")

    @model_validator(mode="after")
    def _one_group(self) -> DownloadFilesIn:
        groups = [
            bool(self.product or self.site_codes or self.start_month),
            bool(self.prototype_uuid),
            bool(self.spec_number),
        ]
        if sum(groups) != 1:
            raise ValueError(
                "pass exactly one selector group: product+site_codes+start_month, prototype_uuid, "
                "or spec_number"
            )
        if groups[0] and not (self.product and self.site_codes and self.start_month):
            raise ValueError("data downloads need product, site_codes and start_month")
        return self


@register_tool(
    "neon_download_files",
    title="Download NEON files",
    description=(
        "Download data files (or package ZIPs), a prototype dataset's files, or a NEON document into the "
        "configured download directory (stdio only; data files need a token). The plan is checked against "
        "file/byte caps before any transfer; MD5s are verified; identical existing files are skipped. "
        "Next: read the CSVs (pandas.read_csv) and cite with neon_get_citation."
    ),
    input_model=DownloadFilesIn,
    output_model=DownloadReport,
    surface="data",
    endpoints=[
        "GET /data/package/{productCode}/{siteCode}/{yearMonth}",
        "GET /prototype/data/{uuid}",
        "GET /documents/{specNumber}",
        "POST /data/query",
    ],
    requires_token=True,
    token_check="handler",
    transports=("stdio",),
    read_only=False,
    idempotent=True,
    needs_downloads=True,
)
async def neon_download_files(args: DownloadFilesIn, ctx: ToolContext) -> DownloadReport:
    if ctx.transport != "stdio":
        raise ToolError(
            "not_available_in_http_mode",
            "Downloads write to the server's disk and are only available over stdio.",
            hint="Use neon_list_files and fetch the signed URLs on the client.",
        )
    if not ctx.config.effective_downloads_enabled(ctx.transport):
        raise ToolError("feature_unavailable", "Downloads are disabled (downloads.enabled=false).")
    manager = DownloadManager(ctx.config.downloads, ctx.client)
    planned: list[PlannedFile] = []
    token = None
    resolved: list[Resolved] = []
    notes: list[str] = []
    code = None
    if args.prototype_uuid:
        try:
            env = await ctx.client.get_json(
                f"/prototype/data/{args.prototype_uuid}",
                token=ctx.token,
                stats=ctx.stats,
                cache="data",
            )
        except NeonApiError as exc:
            raise api_error(
                exc, entity="prototype dataset", identifier=args.prototype_uuid
            ) from None
        wanted = set(args.file_names or [])
        for f in null_list((env.data or {}).get("files")):
            name = str(f.get("fileName") or f.get("name") or "")
            if wanted and name not in wanted and f.get("name") not in wanted:
                continue
            if f.get("url"):
                planned.append(
                    PlannedFile(
                        url=str(f["url"]),
                        name=name,
                        size=f.get("size"),
                        md5=f.get("md5"),
                        rel_dir=PurePosixPath("prototype", args.prototype_uuid),
                    )
                )
        if wanted and not planned:
            raise ToolError("not_found", "None of the requested file_names are in the dataset.")
    elif args.spec_number:
        planned.append(
            PlannedFile(
                url=ctx.client.url_for(f"/documents/{args.spec_number}"),
                name=f"{args.spec_number}.pdf",
                size=None,
                md5=None,
                rel_dir=PurePosixPath("documents"),
            )
        )
    else:
        token = require_token(ctx, endpoint="GET /data")
        code, sites, start, end, data, resolved, _ = await _collect(args, ctx)
        if args.as_zip:
            months = MonthRanges.from_ranges([f"{start}/{end}"]).months()
            present = {(r.site_code, r.month) for r in data.site_months}
            for site in sites:
                for month in months:
                    if (site, month) not in present:
                        continue
                    planned.append(
                        PlannedFile(
                            url=ctx.client.url_for(
                                f"/data/package/{code}/{site}/{month}?package={args.package}"
                            ),
                            name=f"NEON.{code}.{site}.{month}.{args.package}.zip",
                            size=None,
                            md5=None,
                            rel_dir=PurePosixPath(code, site, month),
                            requires_token=True,
                        )
                    )
        else:
            for f in sort_files(data.files):
                if f.url:
                    planned.append(
                        PlannedFile(
                            url=f.url,
                            name=f.name,
                            size=f.size,
                            md5=f.md5,
                            rel_dir=PurePosixPath(code, f.site_code, f.month),
                        )
                    )
        if not planned:
            raise ToolError(
                "not_found",
                "No files match the selectors.",
                hint="Check with neon_list_files first.",
            )
    started = time.monotonic()
    plan = manager.plan(
        planned, dest_subdir=args.dest_subdir, if_exists=args.if_exists, max_bytes=args.max_bytes
    )
    results = await manager.execute(plan, token=token, stats=ctx.stats)
    failed = [r for r in results if r.status == "failed"]
    if failed:
        notes.append(f"{len(failed)} file(s) failed; see files[].error.")
    steps = []
    csv = next((r.path for r in results if r.status != "failed" and r.name.endswith(".csv")), None)
    if csv:
        steps.append(f"pandas.read_csv('{csv}')")
    if code:
        steps.append(f"neon_get_citation(product='{code}')")
        steps.append(
            "neonutilities.stack_by_table() can merge many site-month CSVs (optional, outside neon-mcp)"
        )
    elif args.prototype_uuid:
        steps.append(f"neon_get_citation(prototype_uuid='{args.prototype_uuid}')")
    return DownloadReport(
        download_dir=str(manager.root),
        requested=len(planned),
        files=[
            DownloadedFileOut(
                path=r.path,
                name=r.name,
                size=r.size,
                md5_verified=r.md5_verified,
                status=r.status,
                error=r.error,
            )
            for r in results
        ],
        totals=DownloadTotals(
            files=sum(1 for r in results if r.status == "downloaded"),
            bytes=sum(r.size or 0 for r in results if r.status == "downloaded"),
            seconds=round(time.monotonic() - started, 3),
        ),
        resolved=resolved,
        notes=notes,
        next_steps=steps,
        source=source(ctx),
    )
