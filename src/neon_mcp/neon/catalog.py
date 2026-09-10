"""Product and site catalogs: fetched once, projected immediately, indexed.

The full REST lists are enormous (``/products`` 30 MB, ``/sites`` 27 MB), so
the default path selects only the needed fields over GraphQL (about 3.6 MB
and 0.6 MB, verified 2026-09-10) and projects them into immutable records.
REST is the fallback whenever GraphQL fails, times out, answers with
``errors`` and no ``data``, or drops an expected field; a circuit breaker
stops trying GraphQL for a cooldown after repeated failures.

Fields GraphQL lacks are derived and listed in ``source.derived``:
``productScienceTeamAbbr`` (the parenthesised suffix of
``productScienceTeam``), ``productCategory`` (``Level N Data Product``),
``productCodeLong`` and ``productCodePresentation``.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

import structlog

from neon_mcp.errors import NeonApiError, ToolError
from neon_mcp.neon import gql_queries as gq
from neon_mcp.neon.months import MonthRanges
from neon_mcp.projections.common import haversine_km, product_level, team_abbr

if TYPE_CHECKING:
    from neon_mcp.config import Config
    from neon_mcp.context import UpstreamStats
    from neon_mcp.neon.auth import Token
    from neon_mcp.neon.cache import TTLCache
    from neon_mcp.neon.client import NeonClient

T = TypeVar("T")
log = structlog.get_logger("neon_mcp.catalog")

DERIVED_PRODUCT_FIELDS: tuple[str, ...] = (
    "productScienceTeamAbbr",
    "productCategory",
    "productCodeLong",
    "productCodePresentation",
)
_PRODUCT_CODE_RE = re.compile(r"DP([0-4])\.(\d{5})(?:\.(\d{3}))?", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
Warmth = Literal["cold", "warming", "warm", "degraded"]


def words(text: str | None) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def normalize_product_code(text: str | None) -> str | None:
    """``DP1.10003``, ``neon.dp1.10003.001``, ``NEON.DOM.SITE.DP1.10003.001`` -> ``DP1.10003.001``."""
    if not text:
        return None
    match = _PRODUCT_CODE_RE.search(text.strip())
    if not match:
        return None
    return f"DP{match.group(1)}.{match.group(2)}.{match.group(3) or '001'}"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseRef:
    release: str
    generation_date: str | None
    url: str | None
    doi_url: str | None
    doi_generation_date: str | None


@dataclass(frozen=True)
class SpecRef:
    spec_number: str
    description: str | None
    spec_type: str | None
    spec_size: int | None


@dataclass(frozen=True)
class ProductRecord:
    product_code: str
    product_code_long: str
    product_code_presentation: str
    product_name: str
    product_description: str
    product_status: str
    product_science_team: str
    product_science_team_abbr: str | None
    product_category: str
    level: int
    product_publication_format_type: str | None
    product_has_expanded: bool
    themes: tuple[str, ...]
    keywords: tuple[str, ...]
    releases: tuple[ReleaseRef, ...]
    specs: tuple[SpecRef, ...]
    months_by_site: Mapping[str, MonthRanges]

    def site_codes(self) -> tuple[str, ...]:
        return tuple(sorted(code for code, months in self.months_by_site.items() if months))

    def all_months(self) -> MonthRanges:
        total = MonthRanges()
        for months in self.months_by_site.values():
            total = total.union(months)
        return total

    def latest_release(self) -> str | None:
        tags = [r.release for r in self.releases if r.release]
        return max(tags) if tags else None

    def site_month_count(self) -> int:
        return sum(m.count() for m in self.months_by_site.values())


@dataclass(frozen=True)
class SiteRecord:
    site_code: str
    site_name: str
    site_description: str
    site_type: str
    latitude: float | None
    longitude: float | None
    state_code: str
    state_name: str
    domain_code: str
    domain_name: str
    deims_id: str | None
    releases: tuple[str, ...]
    product_codes: tuple[str, ...]
    product_titles: Mapping[str, str]

    def latest_release(self) -> str | None:
        return max(self.releases) if self.releases else None


def _spec_size(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def product_record(raw: Mapping[str, Any]) -> ProductRecord:
    """Normalise one REST or GraphQL product object (REST values win; else derived)."""
    code = str(raw.get("productCode") or "")
    team = str(raw.get("productScienceTeam") or "")
    level = product_level(code)
    releases = tuple(
        ReleaseRef(
            release=str(r.get("release") or ""),
            generation_date=r.get("generationDate"),
            url=r.get("url"),
            doi_url=(r.get("productDoi") or {}).get("url"),
            doi_generation_date=(r.get("productDoi") or {}).get("generationDate"),
        )
        for r in (raw.get("releases") or [])
        if isinstance(r, Mapping)
    )
    specs = tuple(
        sorted(
            (
                SpecRef(
                    spec_number=str(s.get("specNumber") or ""),
                    description=s.get("specDescription"),
                    spec_type=s.get("specType"),
                    spec_size=_spec_size(s.get("specSize")),
                )
                for s in (raw.get("specs") or [])
                if isinstance(s, Mapping) and s.get("specNumber")
            ),
            key=lambda spec: spec.spec_number,
        )
    )
    months_by_site = {
        str(s.get("siteCode")): MonthRanges.from_months(s.get("availableMonths") or [])
        for s in (raw.get("siteCodes") or [])
        if isinstance(s, Mapping) and s.get("siteCode")
    }
    return ProductRecord(
        product_code=code,
        product_code_long=str(raw.get("productCodeLong") or f"NEON.DOM.SITE.{code}"),
        product_code_presentation=str(
            raw.get("productCodePresentation") or "NEON." + code.rsplit(".", 1)[0]
        ),
        product_name=str(raw.get("productName") or ""),
        product_description=str(raw.get("productDescription") or ""),
        product_status=str(raw.get("productStatus") or ""),
        product_science_team=team,
        product_science_team_abbr=raw.get("productScienceTeamAbbr") or team_abbr(team),
        product_category=str(raw.get("productCategory") or f"Level {level} Data Product"),
        level=level,
        product_publication_format_type=raw.get("productPublicationFormatType"),
        product_has_expanded=bool(raw.get("productHasExpanded")),
        themes=tuple(raw.get("themes") or ()),
        keywords=tuple(raw.get("keywords") or ()),
        releases=releases,
        specs=specs,
        months_by_site=months_by_site,
    )


def site_record(raw: Mapping[str, Any]) -> SiteRecord:
    products = [p for p in (raw.get("dataProducts") or []) if isinstance(p, Mapping)]
    return SiteRecord(
        site_code=str(raw.get("siteCode") or ""),
        site_name=str(raw.get("siteName") or ""),
        site_description=str(raw.get("siteDescription") or ""),
        site_type=str(raw.get("siteType") or ""),
        latitude=raw.get("siteLatitude"),
        longitude=raw.get("siteLongitude"),
        state_code=str(raw.get("stateCode") or ""),
        state_name=str(raw.get("stateName") or ""),
        domain_code=str(raw.get("domainCode") or ""),
        domain_name=str(raw.get("domainName") or ""),
        deims_id=raw.get("deimsId"),
        releases=tuple(
            sorted(
                str(r.get("release"))
                for r in (raw.get("releases") or [])
                if isinstance(r, Mapping) and r.get("release")
            )
        ),
        product_codes=tuple(
            sorted(str(p.get("dataProductCode")) for p in products if p.get("dataProductCode"))
        ),
        product_titles={
            str(p.get("dataProductCode")): str(p.get("dataProductTitle") or "")
            for p in products
            if p.get("dataProductCode")
        },
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    code: str
    label: str
    score: float


@dataclass
class SearchResult(Generic[T]):
    total: int
    items: list[tuple[T, float, list[str]]]
    did_you_mean: list[str] | None = None


@dataclass(frozen=True)
class ProductQuery:
    query: str | None = None
    theme: str | None = None
    science_team: str | None = None
    status: str = "ACTIVE"
    level: int | None = None
    has_expanded: bool | None = None
    site_code: str | None = None
    domain_sites: frozenset[str] | None = None
    available_from: str | None = None
    available_to: str | None = None
    sort: str = "relevance"


@dataclass(frozen=True)
class SiteQuery:
    query: str | None = None
    domain_code: str | None = None
    state_code: str | None = None
    site_type: str | None = None
    product_sites: frozenset[str] | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 100.0


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _word_hit(word: str, vocab: set[str]) -> bool:
    return word in vocab or any(_fuzzy_ratio(word, v) >= 0.85 for v in vocab)


def _name_score(query: str, name: str, extra_words: Iterable[str] = ()) -> float:
    """0..1 similarity between free text and a record name, driven by word coverage.

    Every query word must be accounted for before a score can reach the 0.75
    acceptance threshold, so "Blue Ridge" does not resolve to "Blue River"
    merely because the strings look alike.
    """
    q_words = words(query)
    n_words = words(name)
    if not q_words or not n_words:
        return 0.0
    q, n = " ".join(q_words), " ".join(n_words)
    if q == n:
        return 1.0
    if f" {q} " in f" {n} ":
        return 0.95 if n.startswith(q) else 0.9
    name_vocab = set(n_words)
    extra_vocab = {w for text in extra_words for w in words(text)}
    name_hits = sum(1 for w in q_words if _word_hit(w, name_vocab))
    extra_hits = sum(
        1 for w in q_words if not _word_hit(w, name_vocab) and _word_hit(w, extra_vocab)
    )
    if name_hits == len(q_words):
        return 0.85
    if name_hits + extra_hits == len(q_words) and name_hits > 0:
        return 0.78
    coverage = (name_hits + 0.5 * extra_hits) / len(q_words)
    return round(0.3 + 0.3 * coverage, 3)


class ProductIndex:
    def __init__(
        self,
        records: Sequence[ProductRecord],
        *,
        source: Literal["graphql", "rest"],
        release: str | None,
        built_at: float,
    ) -> None:
        self.records: tuple[ProductRecord, ...] = tuple(
            sorted(records, key=lambda r: r.product_code)
        )
        self.source = source
        self.release = release
        self.built_at = built_at
        self._by_code = {r.product_code: r for r in self.records}
        self._spec_index: dict[str, tuple[SpecRef, list[str]]] = {}
        for rec in self.records:
            for spec in rec.specs:
                _ref, codes = self._spec_index.setdefault(spec.spec_number, (spec, []))
                codes.append(rec.product_code)

    @classmethod
    def from_graphql(
        cls, payload: Mapping[str, Any], *, release: str | None, built_at: float = 0.0
    ) -> ProductIndex:
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        rows = data.get("products") if isinstance(data, Mapping) else None
        return cls(
            [product_record(r) for r in rows or []],
            source="graphql",
            release=release,
            built_at=built_at,
        )

    @classmethod
    def from_rest(cls, payload: Any, *, release: str | None, built_at: float = 0.0) -> ProductIndex:
        rows = payload.get("data") if isinstance(payload, Mapping) else payload
        return cls(
            [product_record(r) for r in rows or []],
            source="rest",
            release=release,
            built_at=built_at,
        )

    def __len__(self) -> int:
        return len(self.records)

    def by_code(self, code: str) -> ProductRecord | None:
        return self._by_code.get(code)

    def normalize_code(self, text: str) -> str | None:
        code = normalize_product_code(text)
        return code if code and code in self._by_code else None

    def spec_lookup(self, spec_number: str) -> tuple[SpecRef | None, list[str]]:
        found = self._spec_index.get(spec_number)
        return (found[0], sorted(found[1])) if found else (None, [])

    def _score(
        self, rec: ProductRecord, q: str, tokens: list[str]
    ) -> tuple[float, list[str]] | None:
        name_words = set(words(rec.product_name))
        desc_words = set(words(rec.product_description))
        kw_lower = [k.lower() for k in rec.keywords]
        kw_words = {w for k in kw_lower for w in words(k)}
        theme_words = {w for t in rec.themes for w in words(t)}
        code_l = rec.product_code.lower()
        score = 0.0
        matched: list[str] = []
        name_l = " ".join(words(rec.product_name))
        phrase = " ".join(tokens)
        if len(tokens) > 1 and f" {phrase} " in f" {name_l} ":
            score += 40
            matched.append("name")
        for tok in tokens:
            hit = False
            if tok in code_l:
                score += 20
                hit = True
                matched.append("code")
            if tok in name_words:
                score += 10
                hit = True
                if "name" not in matched:
                    matched.append("name")
            kw_exact = [k for k in kw_lower if tok == k or tok in words(k)]
            if kw_exact:
                score += 8
                hit = True
                matched.append(f"keyword:{kw_exact[0]}")
            elif any(_fuzzy_ratio(tok, w) >= 0.85 for w in kw_words):
                score += 6
                hit = True
                matched.append("keyword~")
            if tok in theme_words:
                score += 5
                hit = True
                matched.append("theme")
            if tok in desc_words:
                score += 2
                hit = True
                if "description" not in matched:
                    matched.append("description")
            if not hit:
                if any(_fuzzy_ratio(tok, w) >= 0.85 for w in name_words):
                    score += 6
                    matched.append("name~")
                else:
                    return None  # AND semantics: every token must match somewhere
        return score, list(dict.fromkeys(matched))

    def search(self, q: ProductQuery) -> SearchResult[ProductRecord]:
        records: Iterable[ProductRecord] = self.records
        if q.status != "ALL":
            records = [r for r in records if r.product_status.upper() == q.status]
        if q.theme:
            t = q.theme.lower()
            records = [r for r in records if any(th.lower().startswith(t) for th in r.themes)]
        if q.science_team:
            records = [
                r
                for r in records
                if (r.product_science_team_abbr or "").upper() == q.science_team.upper()
            ]
        if q.level is not None:
            records = [r for r in records if r.level == q.level]
        if q.has_expanded is not None:
            records = [r for r in records if r.product_has_expanded == q.has_expanded]
        if q.site_code:
            records = [r for r in records if r.months_by_site.get(q.site_code)]
        if q.domain_sites is not None:
            records = [r for r in records if any(r.months_by_site.get(s) for s in q.domain_sites)]
        if q.available_from or q.available_to:
            records = [
                r for r in records if r.all_months().overlaps(q.available_from, q.available_to)
            ]
        records = list(records)

        scored: list[tuple[ProductRecord, float, list[str]]]
        did_you_mean: list[str] | None = None
        text = (q.query or "").strip()
        if text:
            exact = normalize_product_code(text)
            if (
                exact
                and len(words(text)) <= 5
                and _PRODUCT_CODE_RE.fullmatch(text.strip().upper().removeprefix("NEON."))
            ):
                scored = [(r, 100.0, ["code"]) for r in records if r.product_code == exact]
            else:
                tokens = words(text)
                scored = []
                for rec in records:
                    res = self._score(rec, text, tokens)
                    if res is not None:
                        scored.append((rec, res[0], res[1]))
                if not scored:
                    did_you_mean = self._did_you_mean(tokens)
        else:
            scored = [(r, 0.0, []) for r in records]

        if q.sort == "productName":
            scored.sort(key=lambda x: (x[0].product_name.lower(), x[0].product_code))
        elif q.sort == "productCode" or not text:
            scored.sort(key=lambda x: x[0].product_code)
        else:
            scored.sort(key=lambda x: (-x[1], x[0].product_code))
        return SearchResult(total=len(scored), items=scored, did_you_mean=did_you_mean)

    def _did_you_mean(self, tokens: list[str]) -> list[str]:
        vocab = sorted(
            {w for r in self.records for k in r.keywords for w in [k.lower()]}
            | {w for r in self.records for w in words(r.product_name) if len(w) > 3}
        )
        out: list[str] = []
        for tok in tokens:
            for match in difflib.get_close_matches(tok, vocab, n=3, cutoff=0.7):
                if match not in out:
                    out.append(match)
        return out[:3]

    @staticmethod
    def facets(records: Sequence[ProductRecord]) -> dict[str, dict[str, int]]:
        themes: Counter[str] = Counter(t for r in records for t in r.themes)
        teams: Counter[str] = Counter(r.product_science_team_abbr or "?" for r in records)
        levels: Counter[str] = Counter(str(r.level) for r in records)
        status: Counter[str] = Counter(r.product_status for r in records)
        return {
            "themes": dict(sorted(themes.items())),
            "scienceTeams": dict(sorted(teams.items())),
            "levels": dict(sorted(levels.items())),
            "productStatus": dict(sorted(status.items())),
        }

    def fuzzy_candidates(self, text: str, n: int = 8) -> list[Candidate]:
        code = normalize_product_code(text)
        if code and code in self._by_code:
            return [Candidate(code, self._by_code[code].product_name, 1.0)]
        cands = [
            Candidate(
                r.product_code,
                r.product_name,
                round(_name_score(text, r.product_name, r.keywords), 3),
            )
            for r in self.records
        ]
        cands = [c for c in cands if c.score > 0.3]
        cands.sort(key=lambda c: (-c.score, c.code))
        return cands[:n]


class SiteIndex:
    def __init__(
        self,
        records: Sequence[SiteRecord],
        *,
        source: Literal["graphql", "rest"],
        release: str | None,
        built_at: float,
    ) -> None:
        self.records: tuple[SiteRecord, ...] = tuple(sorted(records, key=lambda r: r.site_code))
        self.source = source
        self.release = release
        self.built_at = built_at
        self._by_code = {r.site_code: r for r in self.records}

    @classmethod
    def from_graphql(
        cls, payload: Mapping[str, Any], *, release: str | None, built_at: float = 0.0
    ) -> SiteIndex:
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        rows = data.get("sites") if isinstance(data, Mapping) else None
        return cls(
            [site_record(r) for r in rows or []],
            source="graphql",
            release=release,
            built_at=built_at,
        )

    @classmethod
    def from_rest(cls, payload: Any, *, release: str | None, built_at: float = 0.0) -> SiteIndex:
        rows = payload.get("data") if isinstance(payload, Mapping) else payload
        return cls(
            [site_record(r) for r in rows or []], source="rest", release=release, built_at=built_at
        )

    def __len__(self) -> int:
        return len(self.records)

    def by_code(self, code: str) -> SiteRecord | None:
        return self._by_code.get(code.upper())

    def codes(self) -> frozenset[str]:
        return frozenset(self._by_code)

    def domains(self) -> dict[str, str]:
        return {
            r.domain_code: r.domain_name for r in sorted(self.records, key=lambda r: r.domain_code)
        }

    def domain_sites(self, domain_code: str) -> frozenset[str]:
        return frozenset(r.site_code for r in self.records if r.domain_code == domain_code)

    def nearest(self, lat: float, lon: float, radius_km: float) -> list[tuple[SiteRecord, float]]:
        out = [
            (r, round(haversine_km(lat, lon, r.latitude, r.longitude), 1))
            for r in self.records
            if r.latitude is not None and r.longitude is not None
        ]
        return sorted([x for x in out if x[1] <= radius_km], key=lambda x: (x[1], x[0].site_code))

    def search(self, q: SiteQuery) -> SearchResult[SiteRecord]:
        records: list[SiteRecord] = list(self.records)
        if q.domain_code:
            records = [r for r in records if r.domain_code == q.domain_code]
        if q.state_code:
            records = [r for r in records if r.state_code.upper() == q.state_code.upper()]
        if q.site_type:
            records = [r for r in records if r.site_type.upper() == q.site_type.upper()]
        if q.product_sites is not None:
            records = [r for r in records if r.site_code in q.product_sites]
        distances: dict[str, float] = {}
        if q.latitude is not None and q.longitude is not None:
            near = {r.site_code: d for r, d in self.nearest(q.latitude, q.longitude, q.radius_km)}
            records = [r for r in records if r.site_code in near]
            distances = near

        text = (q.query or "").strip()
        scored: list[tuple[SiteRecord, float, list[str]]] = []
        did_you_mean: list[str] | None = None
        if text:
            tokens = words(text)
            phrase = " ".join(tokens)
            for rec in records:
                name_l = " ".join(words(rec.site_name))
                name_words = set(name_l.split())
                other = (
                    set(words(rec.site_description))
                    | set(words(rec.state_name))
                    | set(words(rec.domain_name))
                )
                score = 0.0
                matched: list[str] = []
                if rec.site_code.lower() == phrase:
                    score += 100
                    matched.append("code")
                if len(tokens) > 1 and f" {phrase} " in f" {name_l} ":
                    score += 40
                    matched.append("name")
                ok = True
                for tok in tokens:
                    if tok == rec.site_code.lower():
                        continue
                    if tok in name_words:
                        score += 10
                        if "name" not in matched:
                            matched.append("name")
                    elif tok in other or tok in (rec.state_code.lower(), rec.domain_code.lower()):
                        score += 6
                        matched.append("location")
                    elif any(_fuzzy_ratio(tok, w) >= 0.8 for w in name_words):
                        score += 20 * max(_fuzzy_ratio(tok, w) for w in name_words)
                        matched.append("name~")
                    else:
                        ok = False
                        break
                if ok:
                    scored.append((rec, score, sorted(set(matched), key=matched.index)))
            if not scored:
                vocab = sorted({w for r in self.records for w in words(r.site_name) if len(w) > 3})
                did_you_mean = [
                    m
                    for tok in tokens
                    for m in difflib.get_close_matches(tok, vocab, n=2, cutoff=0.7)
                ][:3]
            scored.sort(key=lambda x: (-x[1], distances.get(x[0].site_code, 0.0), x[0].site_code))
        else:
            scored = [(r, 0.0, []) for r in records]
            if distances:
                scored.sort(key=lambda x: (distances[x[0].site_code], x[0].site_code))
        return SearchResult(total=len(scored), items=scored, did_you_mean=did_you_mean)

    @staticmethod
    def facets(records: Sequence[SiteRecord]) -> dict[str, dict[str, int]]:
        return {
            "domains": dict(sorted(Counter(r.domain_code for r in records).items())),
            "states": dict(sorted(Counter(r.state_code for r in records).items())),
            "siteTypes": dict(sorted(Counter(r.site_type for r in records).items())),
        }

    def fuzzy_candidates(self, text: str, n: int = 8) -> list[Candidate]:
        upper = text.strip().upper()
        if upper in self._by_code:
            return [Candidate(upper, self._by_code[upper].site_name, 1.0)]
        cands = [
            Candidate(
                r.site_code,
                r.site_name,
                round(_name_score(text, r.site_name.replace(" NEON", ""), (r.state_name,)), 3),
            )
            for r in self.records
        ]
        cands = [c for c in cands if c.score > 0.3]
        cands.sort(key=lambda c: (-c.score, c.code))
        return cands[:n]


# ---------------------------------------------------------------------------
# Catalog service
# ---------------------------------------------------------------------------


@dataclass
class CatalogStats:
    products: Warmth = "cold"
    sites: Warmth = "cold"
    source: Literal["graphql", "rest"] | None = None
    age_s: int | None = None
    graphql_fallbacks: int = 0
    breaker_open: bool = False


@dataclass
class _Breaker:
    failures: int = 0
    open_until: float = 0.0


def _graphql_not_found(payload: Mapping[str, Any]) -> str | None:
    for err in payload.get("errors") or []:
        message = str(err.get("message", ""))
        if re.search(r"not\s+found", message, re.IGNORECASE):
            return message
    return None


@dataclass
class _Build(Generic[T]):
    index: T
    fallback_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Catalog:
    """Cached access to catalog-shaped NEON resources."""

    def __init__(
        self, client: NeonClient, cache: TTLCache, config: Config, *, clock: Any = time.monotonic
    ) -> None:
        self.client = client
        self.cache = cache
        self.config = config
        self._clock = clock
        self._breaker = _Breaker()
        self._fallbacks = 0
        self._warmth: dict[str, Warmth] = {"products": "cold", "sites": "cold"}
        self._last_source: Literal["graphql", "rest"] | None = None
        self._last_built: float | None = None

    # ---------------------------------------------------------------- breaker

    def graphql_available(self) -> bool:
        return self.config.neon.prefer_graphql and self._clock() >= self._breaker.open_until

    def _graphql_failed(self, query: str, reason: str, missing: Sequence[str] = ()) -> None:
        self._fallbacks += 1
        self._breaker.failures += 1
        if self._breaker.failures >= self.config.neon.graphql_breaker_failures:
            self._breaker.open_until = self._clock() + self.config.neon.graphql_breaker_cooldown_s
        log.warning(
            "neon.graphql_fallback",
            query=query,
            reason=reason,
            missing_fields=list(missing),
            breaker_open=self._clock() < self._breaker.open_until,
        )

    def _graphql_ok(self) -> None:
        self._breaker.failures = 0
        self._breaker.open_until = 0.0

    async def _graphql_rows(
        self,
        query: gq.GqlQuery,
        variables: Mapping[str, Any],
        *,
        token: Token | None,
        stats: UpstreamStats | None,
        cache: Any = None,
        timeout_s: float | None = None,
    ) -> list[dict[str, Any]] | None:
        """Run a catalog GraphQL query; ``None`` means "fall back to REST"."""
        if not self.graphql_available():
            return None
        try:
            env = await self.client.graphql(
                query,
                variables,
                token=token,
                stats=stats,
                cache=cache,
                timeout_s=timeout_s or self.config.neon.catalog_read_timeout_s,
            )
        except (NeonApiError, ToolError) as exc:
            self._graphql_failed(query.name, type(exc).__name__)
            return None
        payload = env.data
        if payload.get("errors") and not (payload.get("data") or {}).get(query.root):
            if _graphql_not_found(payload):
                return (
                    None  # e.g. unknown release: let REST produce the canonical 400 + validReleases
                )
            self._graphql_failed(query.name, "errors")
            return None
        missing = gq.check_expected_fields(query, payload)
        if missing:
            self._graphql_failed(query.name, "drift", missing)
            return None
        self._graphql_ok()
        rows = (payload.get("data") or {}).get(query.root) or []
        return [r for r in rows if isinstance(r, dict)]

    # ---------------------------------------------------------------- indexes

    async def products(
        self,
        *,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> ProductIndex:
        async def build() -> ProductIndex:
            self._warmth["products"] = (
                "warming" if self._warmth["products"] == "cold" else self._warmth["products"]
            )
            rows = await self._graphql_rows(
                gq.PRODUCTS_CATALOG, {"release": release}, token=token, stats=stats
            )
            if rows is not None:
                index = ProductIndex(
                    [product_record(r) for r in rows],
                    source="graphql",
                    release=release,
                    built_at=self._clock(),
                )
            else:
                env = await self.client.get_json(
                    "/products",
                    {"release": release},
                    token=token,
                    stats=stats,
                    timeout_s=self.config.neon.catalog_read_timeout_s,
                )
                index = ProductIndex.from_rest(env.data, release=release, built_at=self._clock())
            self._warmth["products"] = "warm"
            self._last_source, self._last_built = index.source, index.built_at
            return index

        try:
            index, hit = await self.cache.get_or_fetch(
                "catalog", f"index:products:{release or '*'}", build
            )
        except Exception:
            if self._warmth["products"] == "warming":
                self._warmth["products"] = "cold"
            raise
        if hit in ("hit", "stale") and stats is not None:
            stats.cache_hits += 1
        return index

    async def sites(
        self,
        *,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> SiteIndex:
        async def build() -> SiteIndex:
            self._warmth["sites"] = (
                "warming" if self._warmth["sites"] == "cold" else self._warmth["sites"]
            )
            rows = await self._graphql_rows(
                gq.SITES_CATALOG, {"release": release}, token=token, stats=stats
            )
            if rows is not None:
                index = SiteIndex(
                    [site_record(r) for r in rows],
                    source="graphql",
                    release=release,
                    built_at=self._clock(),
                )
            else:
                env = await self.client.get_json(
                    "/sites",
                    {"release": release},
                    token=token,
                    stats=stats,
                    timeout_s=self.config.neon.catalog_read_timeout_s,
                )
                index = SiteIndex.from_rest(env.data, release=release, built_at=self._clock())
            self._warmth["sites"] = "warm"
            return index

        try:
            index, hit = await self.cache.get_or_fetch(
                "catalog", f"index:sites:{release or '*'}", build
            )
        except Exception:
            if self._warmth["sites"] == "warming":
                self._warmth["sites"] = "cold"
            raise
        if hit in ("hit", "stale") and stats is not None:
            stats.cache_hits += 1
        return index

    def peek_sites(self) -> SiteIndex | None:
        value = self.cache.peek("catalog", "index:sites:*")
        return value if isinstance(value, SiteIndex) else None

    def peek_products(self) -> ProductIndex | None:
        value = self.cache.peek("catalog", "index:products:*")
        return value if isinstance(value, ProductIndex) else None

    # ---------------------------------------------------------------- lists

    async def sites_for_release(
        self, release: str, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> list[dict[str, Any]] | None:
        """Site codes/names in a release via GraphQL (never the 22 MB REST list)."""
        if not self.config.neon.prefer_graphql:
            return None
        try:
            env = await self.client.graphql(
                gq.SITES_FOR_RELEASE,
                {"release": release},
                token=token,
                stats=stats,
                cache="catalog",
            )
        except (NeonApiError, ToolError):
            return None
        rows = (env.data.get("data") or {}).get("sites")
        if not isinstance(rows, list):
            return None
        return [r for r in rows if isinstance(r, dict)]

    async def _list(
        self,
        path: str,
        *,
        family: Any = "catalog",
        token: Token | None,
        stats: UpstreamStats | None,
        key: str | None = None,
    ) -> Any:
        env = await self.client.get_json(
            path,
            token=token,
            stats=stats,
            cache=family,
            timeout_s=self.config.neon.catalog_read_timeout_s,
        )
        data = env.data
        if key is not None and isinstance(data, Mapping):
            data = data.get(key)
        return data if data is not None else []

    async def site_locations(
        self, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> list[dict[str, Any]]:
        rows = await self._list("/locations/sites", token=token, stats=stats)
        return [r for r in rows if isinstance(r, dict)]

    async def releases(
        self, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> list[dict[str, Any]]:
        rows = await self._list("/releases", token=token, stats=stats)
        return [r for r in rows if isinstance(r, dict)]

    async def prototype_datasets(
        self, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> list[dict[str, Any]]:
        rows = await self._list("/prototype/datasets", token=token, stats=stats)
        return [r for r in rows if isinstance(r, dict)]

    async def sample_classes(
        self, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> list[dict[str, Any]]:
        rows = await self._list(
            "/samples/supportedClasses",
            family="samples_classes",
            token=token,
            stats=stats,
            key="entries",
        )
        return [r for r in rows if isinstance(r, dict)]

    # ---------------------------------------------------------------- details

    async def product_detail(
        self,
        code: str,
        *,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> dict[str, Any]:
        env = await self.client.get_json(
            f"/products/{code}", {"release": release}, token=token, stats=stats, cache="detail"
        )
        return dict(env.data or {})

    async def site_detail(
        self,
        code: str,
        *,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> dict[str, Any]:
        env = await self.client.get_json(
            f"/sites/{code}", {"release": release}, token=token, stats=stats, cache="detail"
        )
        return dict(env.data or {})

    async def release_detail(
        self, identifier: str, *, token: Token | None = None, stats: UpstreamStats | None = None
    ) -> dict[str, Any]:
        env = await self.client.get_json(
            f"/releases/{identifier}", token=token, stats=stats, cache="detail"
        )
        return dict(env.data or {})

    async def product_availability(
        self,
        codes: Sequence[str],
        *,
        site_codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]:
        """Product rows ``{productCode, productName, siteCodes[{siteCode, availableMonths, availableReleases}]}``."""
        flt: dict[str, Any] = {"productCodes": list(codes)}
        if site_codes:
            flt["siteCodes"] = list(site_codes)
        if start:
            flt["startMonth"] = start
        if end:
            flt["endMonth"] = end
        if release:
            flt["release"] = release
        rows = await self._graphql_rows(
            gq.PRODUCT_AVAILABILITY,
            {"filter": flt},
            token=token,
            stats=stats,
            cache="detail",
            timeout_s=60.0,
        )
        if rows is not None:
            return rows, "graphql"
        out: list[dict[str, Any]] = []
        for code in codes:
            raw = await self.product_detail(code, release=release, token=token, stats=stats)
            sites = [
                s
                for s in (raw.get("siteCodes") or [])
                if isinstance(s, Mapping) and (not site_codes or s.get("siteCode") in site_codes)
            ]
            out.append(
                {
                    "productCode": raw.get("productCode", code),
                    "productName": raw.get("productName"),
                    "siteCodes": [
                        {
                            "siteCode": s.get("siteCode"),
                            "availableMonths": MonthRanges.from_months(
                                s.get("availableMonths") or []
                            )
                            .clip(start, end)
                            .months(),
                            "availableReleases": s.get("availableReleases") or [],
                        }
                        for s in sites
                    ],
                }
            )
        return out, "rest"

    async def site_availability(
        self,
        codes: Sequence[str],
        *,
        product_codes: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        release: str | None = None,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]:
        """Site rows ``{siteCode, siteName, dataProducts[{dataProductCode, ..., availableReleases}]}``."""
        flt: dict[str, Any] = {"siteCodes": list(codes)}
        if product_codes:
            flt["productCodes"] = list(product_codes)
        if start:
            flt["startMonth"] = start
        if end:
            flt["endMonth"] = end
        if release:
            flt["release"] = release
        rows = await self._graphql_rows(
            gq.SITE_AVAILABILITY,
            {"filter": flt},
            token=token,
            stats=stats,
            cache="detail",
            timeout_s=60.0,
        )
        if rows is not None:
            return rows, "graphql"
        out: list[dict[str, Any]] = []
        for code in codes:
            raw = await self.site_detail(code, release=release, token=token, stats=stats)
            prods = [
                p
                for p in (raw.get("dataProducts") or [])
                if isinstance(p, Mapping)
                and (not product_codes or p.get("dataProductCode") in product_codes)
            ]
            out.append(
                {
                    "siteCode": raw.get("siteCode", code),
                    "siteName": raw.get("siteName"),
                    "dataProducts": [
                        {
                            "dataProductCode": p.get("dataProductCode"),
                            "dataProductTitle": p.get("dataProductTitle"),
                            "availableMonths": MonthRanges.from_months(
                                p.get("availableMonths") or []
                            )
                            .clip(start, end)
                            .months(),
                            "availableReleases": p.get("availableReleases") or [],
                        }
                        for p in prods
                    ],
                }
            )
        return out, "rest"

    async def locations_batch(
        self,
        names: Sequence[str],
        *,
        token: Token | None = None,
        stats: UpstreamStats | None = None,
    ) -> tuple[list[dict[str, Any]], Literal["graphql", "rest"]]:
        """Compact location records for up to ~50 names; per-item ``detailError`` on REST failures."""
        if not names:
            return [], "graphql"
        rows = await self._graphql_rows(
            gq.LOCATIONS_BATCH,
            {"query": {"locationNames": list(names)}},
            token=token,
            stats=stats,
            cache="detail",
            timeout_s=60.0,
        )
        if rows is not None:
            return rows, "graphql"
        sem = asyncio.Semaphore(4)

        async def one(name: str) -> dict[str, Any]:
            async with sem:
                try:
                    env = await self.client.get_json(
                        f"/locations/{name}", token=token, stats=stats, cache="locations"
                    )
                    return dict(env.data or {})
                except NeonApiError as exc:
                    return {
                        "locationName": name,
                        "detailError": {
                            "code": "not_found" if exc.status in (400, 404) else "upstream_error",
                            "message": exc.detail[:200],
                        },
                    }

        return list(await asyncio.gather(*(one(n) for n in names))), "rest"

    # ---------------------------------------------------------------- warmth

    async def prewarm(self) -> bool:
        """Build both default indexes; ``False`` (degraded) when either fails."""
        ok = True
        for name, builder in (("products", self.products), ("sites", self.sites)):
            try:
                await builder()
            except Exception as exc:
                ok = False
                self._warmth[name] = "degraded"
                log.warning("catalog.prewarm_failed", index=name, error=type(exc).__name__)
        return ok

    def warmth(self) -> CatalogStats:
        age = int(self._clock() - self._last_built) if self._last_built is not None else None
        return CatalogStats(
            products=self._warmth["products"],
            sites=self._warmth["sites"],
            source=self._last_source,
            age_s=age,
            graphql_fallbacks=self._fallbacks,
            breaker_open=self._clock() < self._breaker.open_until,
        )
