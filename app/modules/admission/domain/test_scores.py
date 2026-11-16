"""Tests & certificates: catalog definitions, entry validation, totals, superscore.

The list of tests (SAT, ACT, IELTS ...) is data edited by administrators; nothing here
is a built-in test. A definition describes sections with ranges, how the total is
derived and whether results of several sittings combine into a superscore.
"""

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Final, Literal, get_args
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.errors import (
    InvalidProofUrlError,
    ScoreInvalidError,
)

Score = Decimal | str
TotalMode = Literal["sum", "mean_int", "mean_half", "manual", "none"]
EntryStatus = Literal["planned", "registered", "taken", "score_received"]

TOTAL_MODES: Final = get_args(TotalMode)
STATUSES: Final = get_args(EntryStatus)
COMPUTED_MODES: Final = ("sum", "mean_int", "mean_half")
LOCALES: Final = ("uz", "ru", "en")
KEY_RE: Final = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
NAME_MAX: Final = 120
LABEL_MAX: Final = 120
LEVEL_MAX: Final = 60
URL_MAX: Final = 500
NOTE_MAX: Final = 500
MAX_ENTRIES: Final = 100
MAX_SECTIONS: Final = 12
_HALF: Final = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class SectionDef:
    """One scored part of a test (or its total): a range and a step."""

    key: str
    names: dict[str, str]
    min: Decimal
    max: Decimal
    step: Decimal
    choices: tuple[str, ...] = ()

    def check(self, raw: object) -> Score:
        """Return the validated value or raise ScoreInvalidError."""
        if self.choices:
            if isinstance(raw, str) and raw in self.choices:
                return raw
            raise _invalid(self.key, None, None)
        value = to_decimal(raw)
        if value is None:
            raise _invalid(self.key, self.min, self.max)
        if not self.min <= value <= self.max or (value - self.min) % self.step:
            raise _invalid(self.key, self.min, self.max)
        return value


@dataclass(frozen=True, slots=True)
class ScoreTest:
    """A kind of test or certificate students can record."""

    id: UUID
    key: str
    names: dict[str, str]
    sections: tuple[SectionDef, ...]
    total: SectionDef | None
    total_mode: TotalMode
    superscore: bool = False
    needs_label: bool = False
    needs_level: bool = False
    position: int = 0
    active: bool = True

    def name(self, locale: str) -> str:
        """Return the name in the locale, English as the fallback."""
        return self.names.get(locale) or self.names.get("en") or self.key


@dataclass(frozen=True, slots=True)
class ScoreEntryDraft:
    """What a student submits for an entry (scores still unvalidated)."""

    test_id: UUID
    status: EntryStatus
    test_date: dt.date | None = None
    registration_deadline: dt.date | None = None
    label: str | None = None
    level: str | None = None
    sections: Mapping[str, object] = field(default_factory=dict)
    total: object | None = None
    certificate_document_id: UUID | None = None
    verification_url: str | None = None
    send_note: str | None = None
    is_official: bool = False


@dataclass(frozen=True, slots=True)
class ScoreEntry:
    """A recorded sitting or certificate of a student."""

    id: UUID
    student_id: UUID
    test_id: UUID
    status: EntryStatus
    test_date: dt.date | None
    registration_deadline: dt.date | None
    label: str | None
    level: str | None
    sections: dict[str, Score]
    total: Score | None
    certificate_document_id: UUID | None
    verification_url: str | None
    send_note: str | None
    is_official: bool
    verified_by: UUID | None
    verified_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    """Best result and superscore of one test over its scored entries."""

    test_id: UUID
    best_entry_id: UUID | None
    best_total: Score | None
    superscore_sections: dict[str, Score] | None
    superscore_total: Score | None


def _invalid(
    field_name: str, lo: Decimal | None, hi: Decimal | None
) -> ScoreInvalidError:
    params: dict[str, Any] = {"field": field_name}
    if lo is not None and hi is not None:
        params["min"], params["max"] = _plain(lo), _plain(hi)
    return ScoreInvalidError(params=params)


def _plain(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def to_decimal(raw: object) -> Decimal | None:
    """Parse a JSON number (or numeric string) into a finite Decimal."""
    if isinstance(raw, bool) or not isinstance(raw, int | float | str | Decimal):
        return None
    try:
        value = Decimal(str(raw))
    except ArithmeticError:
        return None
    return value if value.is_finite() else None


def to_json(value: Score | None) -> int | float | str | None:
    """Serialise a score for JSON storage and the API."""
    return _plain(value) if isinstance(value, Decimal) else value


def from_json(value: object) -> Score | None:
    """Parse a stored score back."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return Decimal(str(value))


def _validate_parts(parts: Sequence[SectionDef]) -> None:
    """Raise ScoreInvalidError when a section or the total is malformed."""
    for part in parts:
        if any(not (part.names.get(loc) or "").strip() for loc in LOCALES):
            raise ScoreInvalidError(params={"field": f"{part.key}.names"})
        if not part.choices and (
            part.step <= 0 or part.min > part.max or (part.max - part.min) % part.step
        ):
            raise ScoreInvalidError(params={"field": part.key})


def validate_definition(test: ScoreTest) -> None:
    """Raise ScoreInvalidError when an administrator's definition is inconsistent."""
    if not KEY_RE.match(test.key):
        raise ScoreInvalidError(params={"field": "key"})
    if any(not (test.names.get(loc) or "").strip() for loc in LOCALES) or any(
        len(n) > NAME_MAX for n in test.names.values()
    ):
        raise ScoreInvalidError(params={"field": "names"})
    if test.total_mode not in TOTAL_MODES or len(test.sections) > MAX_SECTIONS:
        raise ScoreInvalidError(params={"field": "total_mode"})
    keys = [s.key for s in test.sections]
    if len(set(keys)) != len(keys) or any(not KEY_RE.match(k) for k in keys):
        raise ScoreInvalidError(params={"field": "sections"})
    _validate_parts((*test.sections, *((test.total,) if test.total else ())))
    _validate_total(test)


def _validate_total(test: ScoreTest) -> None:
    """Raise ScoreInvalidError when the total mode contradicts the parts."""
    computed = test.total_mode in COMPUTED_MODES
    if computed and (
        not test.sections
        or test.total is None
        or test.total.choices
        or any(s.choices for s in test.sections)
    ):
        raise ScoreInvalidError(params={"field": "total"})
    if test.total_mode == "manual" and test.total is None:
        raise ScoreInvalidError(params={"field": "total"})
    if test.total_mode == "none" and (test.total or test.sections):
        raise ScoreInvalidError(params={"field": "total"})
    if test.superscore and not computed:
        raise ScoreInvalidError(params={"field": "superscore"})


def compute_total(test: ScoreTest, sections: Mapping[str, Score]) -> Score | None:
    """Return the derived total, or None when it is not derivable from the parts."""
    if test.total_mode not in COMPUTED_MODES or not test.sections:
        return None
    parts = [sections.get(s.key) for s in test.sections]
    values = [p for p in parts if isinstance(p, Decimal)]
    if len(values) != len(test.sections):
        return None
    total = sum(values, Decimal(0))
    if test.total_mode == "sum":
        return total
    mean = total / len(values)
    if test.total_mode == "mean_int":
        return (mean + _HALF).to_integral_value(ROUND_FLOOR)
    return ((mean * 2 + _HALF).to_integral_value(ROUND_FLOOR)) / 2


def build_scores(
    test: ScoreTest, raw_sections: Mapping[str, object], raw_total: object | None
) -> tuple[dict[str, Score], Score | None]:
    """Validate the submitted scores of a received result; return parts and total."""
    known = {s.key: s for s in test.sections}
    unknown = sorted(set(raw_sections) - set(known))
    if unknown:
        raise ScoreInvalidError(params={"field": unknown[0]})
    sections = {
        key: known[key].check(raw)
        for key, raw in raw_sections.items()
        if raw is not None
    }
    total = compute_total(test, sections)
    if total is None and test.total is not None and raw_total is not None:
        total = test.total.check(raw_total)
    if test.total_mode == "none":
        return {}, None
    if total is None and not sections:
        raise ScoreInvalidError(params={"field": "total"})
    if test.total_mode == "manual" and total is None:
        raise ScoreInvalidError(params={"field": "total"})
    return sections, total


def validate_entry(
    test: ScoreTest, draft: ScoreEntryDraft
) -> tuple[dict[str, Score], Score | None]:
    """Check a draft against its test; return the validated parts and total."""
    received = draft.status == "score_received"
    if (
        draft.test_date
        and draft.registration_deadline
        and draft.registration_deadline > draft.test_date
    ):
        raise ScoreInvalidError(params={"field": "registration_deadline"})
    label = (draft.label or "").strip()
    level = (draft.level or "").strip()
    if (test.needs_label and not label) or len(label) > LABEL_MAX:
        raise ScoreInvalidError(params={"field": "label"})
    if (test.needs_level and not level) or len(level) > LEVEL_MAX:
        raise ScoreInvalidError(params={"field": "level"})
    if (draft.send_note or "") and len(draft.send_note or "") > NOTE_MAX:
        raise ScoreInvalidError(params={"field": "send_note"})
    if draft.verification_url:
        check_url(draft.verification_url)
    if not received:
        if (
            draft.sections
            or draft.total is not None
            or draft.certificate_document_id
            or draft.verification_url
        ):
            raise ScoreInvalidError(params={"field": "status"})
        return {}, None
    return build_scores(test, draft.sections, draft.total)


def check_url(url: str) -> None:
    """Raise InvalidProofUrlError unless the URL is a plain https address."""
    parts = urlsplit(url)
    if len(url) > URL_MAX or parts.scheme != "https" or not parts.hostname:
        raise InvalidProofUrlError()


def _rank(test: ScoreTest, value: Score) -> Decimal:
    if isinstance(value, Decimal):
        return value
    choices = test.total.choices if test.total else ()
    return Decimal(-choices.index(value)) if value in choices else Decimal(-(10**6))


def summarise(test: ScoreTest, entries: list[ScoreEntry]) -> ScoreSummary:
    """Return the best entry and the superscore over received results."""
    received = [e for e in entries if e.status == "score_received"]
    best: ScoreEntry | None = None
    if not test.needs_label:
        scored = [e for e in received if e.total is not None]
        if scored:
            best = max(
                scored,
                key=lambda e: (
                    _rank(test, e.total),  # type: ignore[arg-type]
                    e.test_date or dt.date.min,
                ),
            )
    super_sections: dict[str, Score] | None = None
    super_total: Score | None = None
    with_parts = [e for e in received if e.sections]
    if test.superscore and len(with_parts) >= 2:
        merged: dict[str, Score] = {}
        for sec in test.sections:
            vals = [e.sections[sec.key] for e in with_parts if sec.key in e.sections]
            decimals = [v for v in vals if isinstance(v, Decimal)]
            if decimals:
                merged[sec.key] = max(decimals)
        total = compute_total(test, merged)
        if total is not None:
            super_sections, super_total = merged, total
    return ScoreSummary(
        test_id=test.id,
        best_entry_id=best.id if best else None,
        best_total=best.total if best else None,
        superscore_sections=super_sections,
        superscore_total=super_total,
    )
