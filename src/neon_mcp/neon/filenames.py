"""NEON file-name grammar.

``NEON.D16.ABBY.DP1.00001.001.000.010.030.2DWSD_30min.2023-01.basic.20250128T000000Z.csv``
is domain, site, product code, then (for instrument products) the HOR/VER/TMI
indices, the table, month, package, generation timestamp and extension.
Observational files omit HOR/VER/TMI; readme, variables, sensor positions,
EML and similar support files carry a keyword instead of a table.
:func:`parse_neon_filename` never raises: unknown shapes are kind ``other``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neon_mcp.models.common import FileKind

_PREFIX_RE = re.compile(r"^NEON\.(D\d{2})\.([A-Z]{4})\.(DP\d\.\d{5}\.\d{3})\.(.+)$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_TIMESTAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
_INDEX_RE = re.compile(r"^\d{3}$")
_KEYWORDS: tuple[tuple[str, FileKind], ...] = (
    ("readme", "readme"),
    ("variables", "variables"),
    ("sensor_positions", "sensor_positions"),
    ("eml", "eml"),
    ("science_review_flags", "science_review_flags"),
    ("categoricalcodes", "categorical_codes"),
    ("validation", "validation"),
)


@dataclass(frozen=True)
class ParsedFilename:
    kind: FileKind
    table: str | None = None
    hor: str | None = None
    ver: str | None = None
    tmi: str | None = None
    domain: str | None = None
    site: str | None = None
    product_code: str | None = None
    month: str | None = None
    package: str | None = None
    timestamp: str | None = None
    ext: str | None = None


def parse_neon_filename(name: str) -> ParsedFilename:
    text = (name or "").strip().rsplit("/", 1)[-1]
    ext = text.rsplit(".", 1)[-1].lower() if "." in text else None
    zipped = ext == "zip"
    match = _PREFIX_RE.match(text)
    if not match:
        return ParsedFilename(kind="package" if zipped else "other", ext=ext)
    domain, site, product, rest = match.groups()
    tokens = rest.split(".")
    if ext is not None and len(tokens) > 1:
        tokens = tokens[:-1]
    month = next((t for t in tokens if _MONTH_RE.match(t)), None)
    timestamp = next((t for t in tokens if _TIMESTAMP_RE.match(t)), None)
    package = next((t for t in tokens if t in ("basic", "expanded")), None)
    base = {
        "domain": domain,
        "site": site,
        "product_code": product,
        "month": month,
        "package": package,
        "timestamp": timestamp,
        "ext": ext,
    }
    if zipped:
        return ParsedFilename(kind="package", **base)
    head = tokens[0].lower() if tokens else ""
    for keyword, kind in _KEYWORDS:
        if head.startswith(keyword):
            table = (
                tokens[0]
                if kind in ("science_review_flags", "categorical_codes", "validation")
                else None
            )
            return ParsedFilename(kind=kind, table=table, **base)
    hor = ver = tmi = None
    rest_tokens = tokens
    if len(tokens) >= 4 and all(_INDEX_RE.match(t) for t in tokens[:3]):
        hor, ver, tmi = tokens[:3]
        rest_tokens = tokens[3:]
    table = rest_tokens[0] if rest_tokens and not _MONTH_RE.match(rest_tokens[0]) else None
    return ParsedFilename(kind="data", table=table, hor=hor, ver=ver, tmi=tmi, **base)
