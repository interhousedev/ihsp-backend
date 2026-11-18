"""Typed international-catalog facts: the key registry and the validation of input.

Every fact has a key with a kind; `clean_fact` turns client input into a `CleanFact`
or raises `CatalogFactInvalidError(fact, reason)`, and `to_row` gives the shape that
is stored in a published fact row.
"""

import datetime as dt
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.admission.domain.catalog_display import (
    INSTITUTION_TYPE,
    SETTING,
    TEST_POLICY,
)
from app.modules.admission.domain.errors import CatalogFactInvalidError
from app.modules.admission.domain.study_fields import canonical_id, labels_of

MONEY_MAX: Final = 1_000_000_000_000
_SPACES = re.compile(r"\s+", re.ASCII)


def clean_name(text: str) -> str:
    """NFC with every run of ASCII whitespace collapsed to one space, stripped."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold_name(text: str) -> str:
    """The comparison key of a name: `clean_name` lower-cased like Postgres `lower`."""
    return clean_name(text).lower()


def has_userinfo(url: str) -> bool:
    """Return whether the URL carries `user[:password]@` before its host."""
    return "@" in urlsplit(url).netloc


FactKind = Literal[
    "bool",
    "int",
    "percent",
    "money",
    "date",
    "text",
    "enum",
    "multi",
    "range",
    "scores",
    "factors",
    "deadlines",
    "study_fields",
]


@dataclass(frozen=True, slots=True)
class FactPart:
    """A sub-key of a `scores` or `factors` fact with its numeric bounds."""

    key: str
    min: float | None = None
    max: float | None = None
    step: float | None = None


@dataclass(frozen=True, slots=True)
class FactSpec:
    """Definition of one fact key."""

    key: str
    group: str
    kind: FactKind
    options: tuple[str, ...] = ()
    parts: tuple[FactPart, ...] = ()
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None


FACT_GROUPS: Final = (
    "overview",
    "selectivity",
    "costs",
    "english",
    "credentials",
    "application",
    "visa",
)
IMPORTANCE: Final = ("very_important", "important", "considered", "not_considered")
PLANS: Final = ("ED", "ED2", "EA", "REA", "SCEA", "RD", "ROLLING", "OTHER")
MAX_DEADLINES: Final = 12
MAX_STUDY_FIELDS: Final = 40
MAX_TEXT: Final = 300
MAX_DEADLINE_NOTE: Final = 200
URL_MAX: Final = 2000
YEAR_MIN: Final = 2000
YEAR_MAX: Final = 2100

FACTOR_KEYS: Final = (
    "rigor",
    "class_rank",
    "gpa",
    "test_scores",
    "essay",
    "recommendations",
    "interview",
    "extracurricular",
    "talent",
    "character",
    "first_generation",
    "alumni_relation",
    "geographical_residence",
    "state_residency",
    "religious",
    "race_ethnic",
    "volunteer",
    "work_experience",
    "level_of_interest",
)
ENGLISH_PARTS: Final = (
    FactPart("toefl_ibt", 0, 120, 1),
    FactPart("toefl_new", 1, 6, 0.5),
    FactPart("ielts", 0, 9, 0.5),
    FactPart("duolingo", 10, 160, 5),
    FactPart("pte", 10, 90, 1),
)

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_CYCLE = re.compile(r"^\d{4}-\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INJECTION = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions|system prompt|"
    r"you are now|give (?:me|this) (?:an? )?A\b|игнорируй|забудь (?:все )?инструкц|"
    r"oldingi ko.rsatmalarni",
    re.IGNORECASE,
)
"""Same pattern as `application.review_checks`: the domain may not import it."""


def _enum(key: str, group: str, options: tuple[str, ...]) -> FactSpec:
    return FactSpec(key, group, "enum", options=options)


def _multi(key: str, group: str, options: tuple[str, ...]) -> FactSpec:
    return FactSpec(key, group, "multi", options=options)


def _flag(key: str, group: str) -> FactSpec:
    return FactSpec(key, group, "bool")


def _money(key: str, group: str) -> FactSpec:
    return FactSpec(key, group, "money", unit="USD" if key.endswith("_usd") else None)


def _build() -> dict[str, FactSpec]:
    specs = (
        _enum("city_type", "overview", tuple(SETTING)),
        _enum("institution_type", "overview", tuple(INSTITUTION_TYPE)),
        FactSpec("fields", "overview", "study_fields"),
        _multi(
            "application_platforms",
            "overview",
            ("common_app", "coalition", "ucas", "uc", "own", "questbridge"),
        ),
        FactSpec(
            "acceptance_rate",
            "selectivity",
            "range",
            min=0,
            max=100,
            unit="percent",
        ),
        FactSpec(
            "intl_acceptance_rate",
            "selectivity",
            "percent",
            min=0,
            max=100,
            unit="percent",
        ),
        FactSpec(
            "intl_share", "selectivity", "percent", min=0, max=100, unit="percent"
        ),
        FactSpec("sat_mid50", "selectivity", "range", min=400, max=1600, step=10),
        FactSpec("act_mid50", "selectivity", "range", min=1, max=36, step=1),
        _enum("test_policy", "selectivity", tuple(TEST_POLICY)),
        FactSpec(
            "admission_factors",
            "selectivity",
            "factors",
            options=IMPORTANCE,
            parts=tuple(FactPart(k) for k in FACTOR_KEYS),
        ),
        _money("intl_tuition_usd", "costs"),
        _money("intl_coa_usd", "costs"),
        _enum(
            "aid_basis",
            "costs",
            ("need_blind_full", "need_aware", "merit_only", "none"),
        ),
        _flag("meets_full_need", "costs"),
        _flag("loan_free", "costs"),
        _flag("merit_for_internationals", "costs"),
        _enum(
            "aid_application_timing",
            "costs",
            ("with_application", "after_admission"),
        ),
        _multi("aid_forms", "costs", ("css_profile", "fafsa", "institutional", "idoc")),
        FactSpec("intl_aid_deadline", "costs", "date"),
        _money("application_fee", "costs"),
        _enum(
            "fee_waiver",
            "costs",
            ("available", "not_available", "international_eligible"),
        ),
        _enum(
            "proof_of_funds", "costs", ("with_application", "after_admission", "none")
        ),
        FactSpec("english_tests", "english", "scores", parts=ENGLISH_PARTS),
        FactSpec("english_waiver", "english", "text"),
        _flag("ukvi_required", "english"),
        _multi(
            "accepted_curricula", "credentials", ("ib", "a_level", "ap", "national")
        ),
        _enum(
            "national_diploma_route",
            "credentials",
            ("direct", "foundation_year", "not_accepted"),
        ),
        _flag("predicted_grades", "credentials"),
        _enum(
            "credential_evaluation",
            "credentials",
            ("not_required", "wes", "ece", "naces_any"),
        ),
        _multi(
            "document_rules",
            "credentials",
            ("certified_translation", "notarisation", "apostille"),
        ),
        _flag("final_results_before_enrolment", "credentials"),
        _enum(
            "interview",
            "application",
            ("none", "optional", "recommended", "required", "third_party"),
        ),
        FactSpec("teacher_recommendations", "application", "int", min=0, max=3),
        _flag("counselor_report", "application"),
        FactSpec("deadlines", "application", "deadlines"),
        _enum("visa_document", "visa", ("i20", "ds2019", "cas", "other")),
    )
    return {s.key: s for s in specs}


FACT_SPECS: Final[dict[str, FactSpec]] = _build()


@dataclass(frozen=True, slots=True)
class CleanFact:
    """A validated fact: `value` has the input shape of its kind."""

    key: str
    value: Any
    source_url: str
    year: int
    note: str | None


def _fail(key: str, reason: str) -> CatalogFactInvalidError:
    return CatalogFactInvalidError(params={"fact": key, "reason": reason})


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _in_bounds(
    v: float,
    lo: float | None,
    hi: float | None,
    step: float | None,
) -> bool:
    if lo is not None and v < lo:
        return False
    if hi is not None and v > hi:
        return False
    if step:
        q = (v - (lo or 0)) / step
        if abs(q - round(q)) > 1e-9:
            return False
    return True


def _clean_url(key: str, url: Any) -> str:
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        raise _fail(key, "source_url")
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise _fail(key, "source_url")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise _fail(key, "source_url") from None
    if parts.scheme != "https" or not host or has_userinfo(url):
        raise _fail(key, "source_url")
    return url


def _clean_text(v: Any, limit: int) -> str | None:
    """NFC, stripped text within the limit; None if not a string or too long."""
    if not isinstance(v, str):
        return None
    text = unicodedata.normalize("NFC", v).strip()
    return text if len(text) <= limit else None


def _clean_note(key: str, note: Any) -> str | None:
    if note is None:
        return None
    text = _clean_text(note, MAX_TEXT)
    if text is None or _INJECTION.search(text):
        raise _fail(key, "note")
    return text or None


def _parse_date(v: Any) -> dt.date | None:
    if not isinstance(v, str) or not _DATE.match(v):
        return None
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        return None


def _scores(key: str, spec: FactSpec, v: Any) -> dict[str, Any]:
    if not isinstance(v, dict) or not v:
        raise _fail(key, "value")
    by_key = {p.key: p for p in spec.parts}
    out: dict[str, Any] = {}
    for part in by_key:  # stored in spec order
        if part not in v:
            continue
        n = v[part]
        p = by_key[part]
        if not _number(n) or not _in_bounds(n, p.min, p.max, p.step):
            raise _fail(key, "value")
        out[part] = n
    if len(out) != len(v):
        raise _fail(key, "value")
    return out


def _factors(key: str, spec: FactSpec, v: Any) -> dict[str, str]:
    if not isinstance(v, dict) or not v:
        raise _fail(key, "value")
    parts = [p.key for p in spec.parts]
    if any(k not in parts for k in v) or any(x not in spec.options for x in v.values()):
        raise _fail(key, "value")
    return {k: v[k] for k in parts if k in v}


def _range(key: str, spec: FactSpec, v: Any) -> dict[str, Any]:
    if _number(v):
        v = {"min": v, "max": v}
    if not isinstance(v, dict) or set(v) != {"min", "max"}:
        raise _fail(key, "value")
    lo, hi = v["min"], v["max"]
    if not _number(lo) or not _number(hi) or lo > hi:
        raise _fail(key, "value")
    for n in (lo, hi):
        if not _in_bounds(n, spec.min, spec.max, spec.step):
            raise _fail(key, "value")
    return {"min": lo, "max": hi}


def _money_value(key: str, spec: FactSpec, v: Any) -> dict[str, Any]:
    if not isinstance(v, dict) or set(v) != {"amount", "currency"}:
        raise _fail(key, "value")
    amount, cur = v["amount"], v["currency"]
    if not _number(amount) or amount < 0 or amount > MONEY_MAX:
        raise _fail(key, "value")
    if not isinstance(cur, str) or not _CURRENCY.match(cur):
        raise _fail(key, "value")
    if spec.unit == "USD" and cur != "USD":
        raise _fail(key, "value")
    return {"amount": amount, "currency": cur}


def _deadline_binding(key: str, x: dict[str, Any], item: dict[str, Any]) -> None:
    binding = x.get("binding")
    if binding is None:
        return
    if not isinstance(binding, bool):
        raise _fail(key, "value")
    item["binding"] = binding


def _deadline_zone(key: str, x: dict[str, Any], item: dict[str, Any]) -> None:
    tz = x.get("time_zone")
    if tz is None:
        return
    if not isinstance(tz, str) or not tz or len(tz) > 64:
        raise _fail(key, "value")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise _fail(key, "value") from None
    item["time_zone"] = tz


def _deadline_note(key: str, x: dict[str, Any], item: dict[str, Any]) -> None:
    if x.get("note") is None:
        return
    note = _clean_text(x["note"], MAX_DEADLINE_NOTE)
    if note is None or _INJECTION.search(note):
        raise _fail(key, "note")
    if note:
        item["note"] = note


def _deadline_item(key: str, x: Any) -> dict[str, Any]:
    if not isinstance(x, dict) or x.get("plan") not in PLANS:
        raise _fail(key, "value")
    if _parse_date(x.get("date")) is None:
        raise _fail(key, "value")
    cycle = x.get("cycle")
    if not isinstance(cycle, str) or not _CYCLE.match(cycle):
        raise _fail(key, "value")
    item: dict[str, Any] = {"plan": x["plan"], "date": x["date"], "cycle": cycle}
    _deadline_binding(key, x, item)
    _deadline_zone(key, x, item)
    _deadline_note(key, x, item)
    return item


def _deadlines(key: str, v: Any) -> list[dict[str, Any]]:
    if not isinstance(v, list) or len(v) > MAX_DEADLINES:
        raise _fail(key, "value")
    return [_deadline_item(key, x) for x in v]


def _study_fields(key: str, v: Any) -> list[str]:
    if not isinstance(v, list) or not v or len(v) > MAX_STUDY_FIELDS:
        raise _fail(key, "value")
    out: list[str] = []
    for raw in v:
        if not isinstance(raw, str) or not raw.strip():
            raise _fail(key, "value")
        cid = canonical_id(raw)
        if cid.startswith("x_"):
            raise _fail(key, "value")
        name = labels_of(cid, raw)
        if name not in out:
            out.append(name)
    return out


def _bool_value(spec: FactSpec, v: Any) -> bool:
    if not isinstance(v, bool):
        raise _fail(spec.key, "value")
    return v


def _number_value(spec: FactSpec, v: Any) -> Any:
    if spec.kind == "int" and (isinstance(v, bool) or not isinstance(v, int)):
        raise _fail(spec.key, "value")
    if not _number(v) or not _in_bounds(v, spec.min, spec.max, spec.step):
        raise _fail(spec.key, "value")
    return v


def _date_value(spec: FactSpec, v: Any) -> Any:
    if _parse_date(v) is None:
        raise _fail(spec.key, "value")
    return v


def _text_value(spec: FactSpec, v: Any) -> str:
    text = _clean_text(v, MAX_TEXT)
    if text is None or not text:
        raise _fail(spec.key, "value")
    if _INJECTION.search(text):
        raise _fail(spec.key, "text")
    return text


def _enum_value(spec: FactSpec, v: Any) -> str:
    if not isinstance(v, str) or v not in spec.options:
        raise _fail(spec.key, "value")
    return v


def _multi_value(spec: FactSpec, v: Any) -> list[str]:
    if (
        not isinstance(v, list)
        or not v
        or any(not isinstance(x, str) or x not in spec.options for x in v)
        or len(set(v)) != len(v)
    ):
        raise _fail(spec.key, "value")
    return [o for o in spec.options if o in v]


_VALUE_CLEANERS: Final[dict[str, Callable[[FactSpec, Any], Any]]] = {
    "bool": _bool_value,
    "int": _number_value,
    "percent": _number_value,
    "money": lambda spec, v: _money_value(spec.key, spec, v),
    "date": _date_value,
    "text": _text_value,
    "enum": _enum_value,
    "multi": _multi_value,
    "range": lambda spec, v: _range(spec.key, spec, v),
    "scores": lambda spec, v: _scores(spec.key, spec, v),
    "factors": lambda spec, v: _factors(spec.key, spec, v),
    "deadlines": lambda spec, v: _deadlines(spec.key, v),
    "study_fields": lambda spec, v: _study_fields(spec.key, v),
}


def _clean_value(spec: FactSpec, v: Any) -> Any:
    cleaner = _VALUE_CLEANERS.get(spec.kind)
    if cleaner is None:
        raise _fail(spec.key, "kind")
    return cleaner(spec, v)


def clean_fact(
    key: str,
    value: Any,
    *,
    source_url: str,
    year: int,
    note: str | None = None,
) -> CleanFact | None:
    """Validate one fact; None when the value is None (the fact is dropped)."""
    if value is None:
        return None
    spec = FACT_SPECS.get(key)
    if spec is None:
        raise _fail(key, "unknown_key")
    url = _clean_url(key, source_url)
    if (
        not isinstance(year, int)
        or isinstance(year, bool)
        or not YEAR_MIN <= year <= YEAR_MAX
    ):
        raise _fail(key, "year")
    clean_note = _clean_note(key, note)
    return CleanFact(key, _clean_value(spec, value), url, year, clean_note)


def clean_facts(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, CleanFact]:
    """Validate `{key: {value, source_url, year, note?}}`; null values are dropped."""
    out: dict[str, CleanFact] = {}
    for key, item in raw.items():
        fact = clean_fact(
            key,
            item.get("value"),
            source_url=item.get("source_url"),  # type: ignore[arg-type]
            year=item.get("year"),  # type: ignore[arg-type]
            note=item.get("note"),
        )
        if fact is not None:
            out[key] = fact
    return out


def to_row(fact: CleanFact) -> tuple[Any, str | None]:
    """Return the stored `(value, unit)` of a fact row."""
    spec = FACT_SPECS[fact.key]
    v = fact.value
    if spec.kind == "money":
        return v["amount"], v["currency"]
    if spec.kind == "percent":
        return v, "percent"
    if spec.kind == "range":
        return {"min": v["min"], "max": v["max"]}, spec.unit
    return v, None
