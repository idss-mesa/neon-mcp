"""Base models, the result envelope, and shared input types.

Naming (DESIGN.md D1): input fields are snake_case in every ``inputSchema``
and also accept NEON's camelCase spelling; output keys are NEON's own
camelCase names wherever a NEON field exists, and neon-mcp's additions are
camelCase too (``nextSteps``, ``page.nextOffset``).
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    AliasChoices,
    AliasGenerator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)
from pydantic.alias_generators import to_camel


def _validation_alias(name: str) -> AliasChoices:
    camel = to_camel(name)
    return AliasChoices(name, camel) if camel != name else AliasChoices(name)


class NeonInput(BaseModel):
    """Base for every tool input: snake_case advertised, camelCase accepted, extras rejected."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        alias_generator=AliasGenerator(validation_alias=_validation_alias),
    )


class NeonOutput(BaseModel):
    """Base for every output object; dumped ``by_alias`` so keys are camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    #: Name of the list field :func:`neon_mcp.registry.fit_to_budget` may shorten.
    budget_list: ClassVar[str | None] = None
    #: Item fields nulled (from the tail) before items are dropped.
    budget_elide_fields: ClassVar[tuple[str, ...]] = ()
    #: Flag set on the payload when elision happened (e.g. ``urls_elided``).
    budget_elide_flag: ClassVar[str | None] = None
    #: The Page field describing ``budget_list``.
    budget_page: ClassVar[str] = "page"


class Page(NeonOutput):
    """Pagination state of one list in a result."""

    total: int | None = Field(None, description="Total items available, when known.")
    returned: int = Field(description="Items in this result.")
    offset: int = Field(description="Offset of the first returned item.")
    limit: int = Field(description="Page size that was applied.")
    truncated: bool = Field(description="True when more items exist beyond this page.")
    next_offset: int | None = Field(
        None, description="Pass as offset to get the next page; absent when there is none."
    )
    truncated_reason: Literal["limit", "budget"] | None = Field(
        None,
        description="'limit' = page size reached; 'budget' = trimmed to the result-size budget.",
    )


class Resolved(NeonOutput):
    """Echo of a fuzzy name-to-code resolution."""

    field: str
    input: str
    code: str
    confidence: float


class Source(NeonOutput):
    """Where a result came from."""

    endpoints: list[str] = Field(
        default_factory=list, description="NEON endpoints called (paths, no query)."
    )
    via: Literal["graphql", "rest", "local", "mixed"] = "rest"
    cached: bool = False
    derived: list[str] = Field(
        default_factory=list,
        description="Fields computed by neon-mcp rather than returned by NEON.",
    )


class ToolResultBase(NeonOutput):
    """Envelope carried by every tool result."""

    resolved: list[Resolved] = Field(
        default_factory=list, description="Fuzzy inputs resolved to NEON codes."
    )
    notes: list[str] = Field(
        default_factory=list, description="Caveats: provisional data, clipping, fallbacks used."
    )
    next_steps: list[str] = Field(default_factory=list, description="Concrete follow-up calls.")
    source: Source | None = None


class MonthRange(NeonOutput):
    """Inclusive first/last month (YYYY-MM)."""

    start: str
    end: str


class Window(NeonOutput):
    """A requested month window."""

    start_month: str | None = None
    end_month: str | None = None


# ---------------------------------------------------------------------------
# Shared input types
# ---------------------------------------------------------------------------

PRODUCT_CODE_PATTERN = r"^DP[0-4]\.\d{5}\.\d{3}$"
SITE_CODE_PATTERN = r"^[A-Z]{4}$"
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
RELEASE_TAG_PATTERN = r"^RELEASE-\d{4}$"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
DOMAIN_PATTERN = r"^D(0[1-9]|1\d|20)$"
SPEC_NUMBER_PATTERN = r"^NEON\.DOC\.\d{6}(v[A-Z]{1,2})?$"
FIRST_MONTH = "2012-01"

PROVISIONAL_MESSAGE = (
    "PROVISIONAL is not a release tag; use the provisional / include_provisional switch instead"
)


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _strip_upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _strip_lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _check_month(value: str) -> str:
    if value < FIRST_MONTH:
        raise ValueError(f"NEON data begin in {FIRST_MONTH}; use a month from {FIRST_MONTH} on")
    return value


def _release_tag(value: Any) -> Any:
    if isinstance(value, str):
        tag = value.strip().upper()
        if tag == "PROVISIONAL":
            raise ValueError(PROVISIONAL_MESSAGE)
        return tag
    return value


def _release_id(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.lower() == "latest":
            return "latest"
        if len(text) == 36 and text.count("-") == 4:
            return text.lower()
        return _release_tag(text)
    return value


ProductCode = Annotated[
    str, BeforeValidator(_strip_upper), StringConstraints(pattern=PRODUCT_CODE_PATTERN)
]
SiteCode = Annotated[
    str, BeforeValidator(_strip_upper), StringConstraints(pattern=SITE_CODE_PATTERN)
]
Month = Annotated[
    str,
    BeforeValidator(_strip),
    StringConstraints(pattern=MONTH_PATTERN),
    AfterValidator(_check_month),
]
ReleaseTag = Annotated[
    str, BeforeValidator(_release_tag), StringConstraints(pattern=RELEASE_TAG_PATTERN)
]
ReleaseId = Annotated[
    str,
    BeforeValidator(_release_id),
    StringConstraints(
        pattern=r"^(RELEASE-\d{4}|latest|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
]
DomainCode = Annotated[
    str, BeforeValidator(_strip_upper), StringConstraints(pattern=DOMAIN_PATTERN)
]
SpecNumber = Annotated[str, BeforeValidator(_strip), StringConstraints(pattern=SPEC_NUMBER_PATTERN)]
Uuid = Annotated[str, BeforeValidator(_strip_lower), StringConstraints(pattern=UUID_PATTERN)]
LocationName = Annotated[
    str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=200)
]
PackageType = Literal["basic", "expanded"]
TaxonTypeCode = Annotated[
    Literal[
        "ALGAE",
        "BEETLE",
        "BIRD",
        "FISH",
        "HERPETOLOGY",
        "MACROINVERTEBRATE",
        "MOSQUITO",
        "MOSQUITO_PATHOGENS",
        "PLANT",
        "SMALL_MAMMAL",
        "TICK",
    ],
    BeforeValidator(_strip_upper),
]
FileKind = Literal[
    "data",
    "variables",
    "readme",
    "sensor_positions",
    "eml",
    "science_review_flags",
    "categorical_codes",
    "validation",
    "package",
    "other",
]

ScienceTeam = Annotated[Literal["AIS", "AOP", "AOS", "TIS", "TOS"], BeforeValidator(_strip_upper)]
ProductStatus = Annotated[
    Literal["ACTIVE", "FUTURE", "RETIRED", "ALL"], BeforeValidator(_strip_upper)
]
SiteType = Annotated[Literal["CORE", "GRADIENT"], BeforeValidator(_strip_upper)]
StateCode = Annotated[str, BeforeValidator(_strip_upper), StringConstraints(pattern=r"^[A-Z]{2}$")]


def start_month_field(description: str = "First month (YYYY-MM).", default: Any = None) -> Any:
    """``start_month``, also accepted as ``startMonth`` / ``startDateMonth`` (NEON's spelling)."""
    return Field(
        default,
        description=description,
        validation_alias=AliasChoices("start_month", "startMonth", "startDateMonth"),
    )


def end_month_field(description: str = "Last month (YYYY-MM); defaults to start_month.") -> Any:
    """``end_month``, also accepted as ``endMonth`` / ``endDateMonth``."""
    return Field(
        None,
        description=description,
        validation_alias=AliasChoices("end_month", "endMonth", "endDateMonth"),
    )
