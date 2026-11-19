"""Staff proposals to change the catalog (§11): reviewed before they go live."""

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.admission.domain.study_fields import is_field_id

ProposalKind = Literal["institution", "scholarship"]
ProposalStatus = Literal["pending", "approved", "rejected"]

INSTITUTION_FIELDS: Final = frozenset(
    {
        "name",
        "name_local",
        "country",
        "city",
        "website_domain",
        "kind",
        "size_band",
        "setting",
        "languages",
        "logo_url",
        "logo_zoom",
        "logo_fit",
        "logo_aspect",
        "aliases",
        "cover_url",
        "programs",
    }
)
SCHOLARSHIP_FIELDS: Final = frozenset(
    {
        "name",
        "provider",
        "institution_id",
        "country",
        "basis",
        "coverage_pct_min",
        "coverage_pct_max",
        "covers",
        "eligibility",
        "url",
        "cycle",
    }
)
FIELDS: Final = {"institution": INSTITUTION_FIELDS, "scholarship": SCHOLARSHIP_FIELDS}
MEDIA_FIELDS: Final = ("logo_url", "cover_url")
"""Institution fields that hold an https image address."""
REQUIRED_ON_CREATE: Final = {
    "institution": frozenset({"name", "country"}),
    "scholarship": frozenset({"name", "provider", "basis"}),
}

ALIASES_MAX: Final = 50
"""Most aliases of one institution."""
_INT_MAX: Final = 2_147_483_647
_KIND_VALUES: Final = ("university", "college", "foundation_provider")
_SETTING_VALUES: Final = ("big_city", "college_town", "campus", "small_city")
_PROVIDER_VALUES: Final = ("institution", "government", "foundation")
_BASIS_VALUES: Final = ("merit", "need", "government", "sports", "work_study")

_Check = Callable[[Any], bool]


def _text(limit: int) -> _Check:
    return lambda v: isinstance(v, str) and 0 < len(v) <= limit


def _one_of(values: tuple[str, ...]) -> _Check:
    return lambda v: isinstance(v, str) and v in values


def _text_list(max_items: int, limit: int) -> _Check:
    return lambda v: (
        isinstance(v, list)
        and len(v) <= max_items
        and all(isinstance(x, str) and 0 < len(x) <= limit for x in v)
    )


def _int_between(lo: int, hi: int) -> _Check:
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _uuid_text(v: Any) -> bool:
    try:
        return isinstance(v, str) and str(UUID(v)) == v.lower()
    except ValueError:
        return False


def _json_object(v: Any) -> bool:
    return isinstance(v, dict) and all(isinstance(k, str) for k in v)


PROGRAMS_MAX: Final = 60
"""Most programs proposed for one institution in one proposal."""
PROGRAM_DEGREES: Final = ("bachelor", "master", "foundation", "other")
PROGRAM_FIELD_IDS_MAX: Final = 8


def _program_ok(p: Any) -> bool:
    allowed = {"school", "name", "degree", "field_ids"}
    if not isinstance(p, dict) or not set(p) <= allowed:
        return False
    school = p.get("school")
    name = p.get("name")
    fields = p.get("field_ids", [])
    return (
        (school is None or (isinstance(school, str) and 0 < len(school) <= 120))
        and isinstance(name, str)
        and 0 < len(name) <= 200
        and p.get("degree") in PROGRAM_DEGREES
        and isinstance(fields, list)
        and len(fields) <= PROGRAM_FIELD_IDS_MAX
        and all(isinstance(f, str) and is_field_id(f) for f in fields)
    )


def _programs(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) <= PROGRAMS_MAX
        and all(_program_ok(p) for p in v)
    )


_FIELD_CHECKS: Final[dict[str, dict[str, _Check]]] = {
    "institution": {
        "name": _text(200),
        "name_local": _text(200),
        "country": lambda v: isinstance(v, str) and len(v) == 2,
        "city": _text(120),
        "website_domain": _text(200),
        "kind": _one_of(_KIND_VALUES),
        "size_band": _text(10),
        "setting": _one_of(_SETTING_VALUES),
        "languages": _text_list(ALIASES_MAX, 100),
        "aliases": _text_list(ALIASES_MAX, 200),
        "programs": _programs,
    },
    "scholarship": {
        "name": _text(200),
        "provider": _one_of(_PROVIDER_VALUES),
        "institution_id": _uuid_text,
        "country": lambda v: isinstance(v, str) and len(v) == 2,
        "basis": _one_of(_BASIS_VALUES),
        "coverage_pct_min": _int_between(0, 100),
        "coverage_pct_max": _int_between(0, 100),
        "covers": _text_list(ALIASES_MAX, 100),
        "eligibility": _json_object,
        "url": _text(2000),
        "cycle": _int_between(2000, 2100),
    },
}
"""Per-kind shape of each field, taken from the columns approval writes it to.

Media fields (`logo_*`, `cover_url`) are checked by the application service."""


def invalid_field(kind: ProposalKind, payload: Mapping[str, Any]) -> str | None:
    """Return the first field whose type, length or value the column cannot hold."""
    checks = _FIELD_CHECKS[kind]
    for key, value in payload.items():
        check = checks.get(key)
        if check is not None and not check(value):
            return key
    return None


@dataclass(frozen=True, slots=True)
class CatalogProposal:
    """One proposal; `target_id` is set when it edits an existing row."""

    id: UUID
    kind: ProposalKind
    target_id: UUID | None
    payload: dict[str, Any]
    source_url: str
    note: str | None
    status: ProposalStatus
    proposed_by: UUID
    created_at: dt.datetime
    lock_version: int = 0
    reviewed_by: UUID | None = None
    reviewed_at: dt.datetime | None = None
    review_note: str | None = None
    applied_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Typed facts `{key: {value, source_url, year, note}}`; never in `payload`."""
    supp_prompts: list[dict[str, Any]] = field(default_factory=list)
    """Supplement prompts `{cycle, prompt, word_limit, required, source_url}`."""

    def missing_on_create(self) -> list[str]:
        """Return the required fields a new row still lacks."""
        if self.target_id is not None:
            return []
        have = {k for k, v in self.payload.items() if v not in (None, "")}
        return sorted(REQUIRED_ON_CREATE[self.kind] - have)
