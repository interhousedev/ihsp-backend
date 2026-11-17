"""Opportunities catalog: exams, certifications, courses, events and recurring ones.

Entries come only from submissions that a platform administrator approved; the
taxonomy (field → subfield → subject) is edited by administrators. Nothing here is
a built-in list of opportunities.
"""

import calendar
import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args
from uuid import UUID

OpportunityKind = Literal[
    "exam", "certification", "course", "event", "recurring", "program", "scholarship"
]
MaterialKind = Literal["link", "lms_course", "alumni", "center"]
TaxonomyLevel = Literal["field", "subfield", "subject"]
SubmissionStatus = Literal["pending", "approved", "rejected"]
SubmitterRole = Literal["student", "staff", "helper", "admin"]
Freq = Literal["YEARLY", "MONTHLY", "WEEKLY"]

KINDS: Final = get_args(OpportunityKind)
AWARD_TYPES: Final = ("scholarship", "fellowship", "grant", "tuition_waiver", "program")
COVERAGES: Final = ("full_tuition", "partial_tuition", "stipend", "cash", "travel")
SCOPES: Final = ("local", "international")
CREDITS: Final = ("none", "possible", "yes")
MATERIAL_KINDS: Final = get_args(MaterialKind)
LEVELS: Final = get_args(TaxonomyLevel)
PARENT_LEVEL: Final[dict[str, str | None]] = {
    "field": None,
    "subfield": "field",
    "subject": "subfield",
}
GRADES: Final = (9, 10, 11, 12)
TITLE_MAX: Final = 200
SUMMARY_MAX: Final = 2000
TEXT_MAX: Final = 300
URL_MAX: Final = 2000
NOTE_MAX: Final = 1000
REASON_MAX: Final = 500
MAX_DATES: Final = 12
MAX_MATERIALS: Final = 20
MAX_SUBJECTS: Final = 10
MAX_PLAN_ITEMS: Final = 60
NAME_MAX: Final = 120
LOCALES: Final = ("uz", "ru", "en")


@dataclass(frozen=True, slots=True)
class TaxonomyNode:
    """One field, subfield or subject; `names` holds uz/ru/en."""

    id: UUID
    level: TaxonomyLevel
    parent_id: UUID | None
    names: dict[str, str]
    position: int = 0


@dataclass(frozen=True, slots=True)
class OpportunityMaterial:
    """A way to prepare: a free link, a local LMS course, an alumnus or a centre."""

    kind: MaterialKind
    title: str
    url: str | None = None
    note: str | None = None
    lms_course_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class OpportunityDraft:
    """What a submitter proposes; validated by `problems`."""

    kind: OpportunityKind
    title: str
    summary: str | None = None
    url: str | None = None
    provider: str | None = None
    subject_ids: tuple[UUID, ...] = ()
    grades: tuple[int, ...] = ()
    registration_deadlines: tuple[dt.date, ...] = ()
    exam_dates: tuple[dt.date, ...] = ()
    last_year_dates: tuple[dt.date, ...] = ()
    recurrence: str | None = None
    lms_course_id: UUID | None = None
    materials: tuple[OpportunityMaterial, ...] = ()
    note: str | None = None
    country: str | None = None
    location: str | None = None
    online: bool = False
    acceptance_rate: float | None = None
    tuition_usd: int | None = None
    logo_url: str | None = None
    host_institution: str | None = None
    duration_weeks: int | None = None
    ranking: int | None = None
    org_id: UUID | None = None
    award_type: str | None = None
    coverage: tuple[str, ...] = ()
    scope: str | None = None
    amount_text: str | None = None
    amount_value: float | None = None
    currency: str | None = None
    essay_required: bool = False
    eligibility: str | None = None
    source_url: str | None = None
    college_credit: str | None = None
    credit_note: str | None = None

    def urls(self) -> list[str]:
        """Every link the draft carries."""
        return [
            u
            for u in [
                self.url,
                self.logo_url,
                self.source_url,
                *(m.url for m in self.materials),
            ]
            if u
        ]

    def problems(self) -> list[str]:
        """Return the names of the invalid fields (empty when valid)."""
        return [
            *self._field_problems(),
            *self._link_problems(),
            *self._scholar_problems(),
        ]

    def _scholar_problems(self) -> list[str]:
        bad: list[str] = []
        if self.award_type is not None and self.award_type not in AWARD_TYPES:
            bad.append("award_type")
        if any(c not in COVERAGES for c in self.coverage):
            bad.append("coverage")
        if self.scope is not None and self.scope not in SCOPES:
            bad.append("scope")
        if self.college_credit is not None and self.college_credit not in CREDITS:
            bad.append("college_credit")
        if self.amount_value is not None and self.amount_value < 0:
            bad.append("amount_value")
        if self.currency is not None and not 3 <= len(self.currency) <= 8:
            bad.append("currency")
        return bad + self._scholar_text_problems()

    def _scholar_text_problems(self) -> list[str]:
        bad = [
            name
            for name in ("amount_text", "currency", "credit_note")
            if (value := getattr(self, name)) is not None and len(value) > TEXT_MAX
        ]
        if self.eligibility is not None and len(self.eligibility) > SUMMARY_MAX:
            bad.append("eligibility")
        return bad

    def _optional_text_problems(self) -> list[str]:
        bad: list[str] = []
        if self.provider is not None and len(self.provider) > TEXT_MAX:
            bad.append("provider")
        if self.note is not None and len(self.note) > NOTE_MAX:
            bad.append("note")
        for name in ("country", "location", "host_institution"):
            value = getattr(self, name)
            if value is not None and len(value) > TEXT_MAX:
                bad.append(name)
        return bad + self._catalog_problems()

    def _catalog_problems(self) -> list[str]:
        bad: list[str] = []
        if self.acceptance_rate is not None and not 0 <= self.acceptance_rate <= 100:
            bad.append("acceptance_rate")
        if self.tuition_usd is not None and self.tuition_usd < 0:
            bad.append("tuition_usd")
        if self.duration_weeks is not None and self.duration_weeks < 1:
            bad.append("duration_weeks")
        if self.ranking is not None and self.ranking < 1:
            bad.append("ranking")
        return bad

    def _field_problems(self) -> list[str]:
        bad: list[str] = []
        if self.kind not in KINDS:
            bad.append("kind")
        if not self.title.strip() or len(self.title) > TITLE_MAX:
            bad.append("title")
        if self.summary is not None and len(self.summary) > SUMMARY_MAX:
            bad.append("summary")
        bad += self._optional_text_problems()
        if len(self.subject_ids) > MAX_SUBJECTS:
            bad.append("subject_ids")
        if any(g not in GRADES for g in self.grades):
            bad.append("grades")
        for name in ("registration_deadlines", "exam_dates", "last_year_dates"):
            if len(getattr(self, name)) > MAX_DATES:
                bad.append(name)
        return bad

    def _link_problems(self) -> list[str]:
        bad: list[str] = []
        if self.kind == "recurring" and not self.recurrence:
            bad.append("recurrence")
        if self.recurrence:
            try:
                parse_rule(self.recurrence)
            except ValueError:
                bad.append("recurrence")
        if len(self.materials) > MAX_MATERIALS or any(
            m.kind not in MATERIAL_KINDS
            or not m.title.strip()
            or len(m.title) > TEXT_MAX
            or (m.note is not None and len(m.note) > NOTE_MAX)
            or (m.kind == "lms_course" and m.lms_course_id is None)
            for m in self.materials
        ):
            bad.append("materials")
        if any(len(u) > URL_MAX for u in self.urls()):
            bad.append("url")
        return bad

    def to_payload(self) -> dict[str, Any]:
        """JSON form stored on a submission."""
        return {
            "kind": self.kind,
            "title": self.title.strip(),
            "summary": self.summary,
            "url": self.url,
            "provider": self.provider,
            "subject_ids": [str(s) for s in self.subject_ids],
            "grades": sorted(set(self.grades)),
            "registration_deadlines": _iso(self.registration_deadlines),
            "exam_dates": _iso(self.exam_dates),
            "last_year_dates": _iso(self.last_year_dates),
            "recurrence": self.recurrence,
            "lms_course_id": str(self.lms_course_id) if self.lms_course_id else None,
            "country": self.country,
            "location": self.location,
            "online": self.online,
            "acceptance_rate": self.acceptance_rate,
            "tuition_usd": self.tuition_usd,
            "logo_url": self.logo_url,
            "host_institution": self.host_institution,
            "duration_weeks": self.duration_weeks,
            "ranking": self.ranking,
            "org_id": str(self.org_id) if self.org_id else None,
            "award_type": self.award_type,
            "coverage": list(self.coverage),
            "scope": self.scope,
            "amount_text": self.amount_text,
            "amount_value": self.amount_value,
            "currency": self.currency,
            "essay_required": self.essay_required,
            "eligibility": self.eligibility,
            "source_url": self.source_url,
            "college_credit": self.college_credit,
            "credit_note": self.credit_note,
            "materials": [
                {
                    "kind": m.kind,
                    "title": m.title.strip(),
                    "url": m.url,
                    "note": m.note,
                    "lms_course_id": str(m.lms_course_id) if m.lms_course_id else None,
                }
                for m in self.materials
            ],
        }

    @classmethod
    def from_payload(
        cls, p: Mapping[str, Any], note: str | None = None
    ) -> "OpportunityDraft":
        """Read the stored JSON form back."""
        return cls(
            kind=p["kind"],
            title=p["title"],
            summary=p.get("summary"),
            url=p.get("url"),
            provider=p.get("provider"),
            subject_ids=tuple(UUID(s) for s in p.get("subject_ids", [])),
            grades=tuple(p.get("grades", [])),
            registration_deadlines=_dates(p.get("registration_deadlines", [])),
            exam_dates=_dates(p.get("exam_dates", [])),
            last_year_dates=_dates(p.get("last_year_dates", [])),
            recurrence=p.get("recurrence"),
            lms_course_id=_uuid(p.get("lms_course_id")),
            materials=tuple(
                OpportunityMaterial(
                    kind=m["kind"],
                    title=m["title"],
                    url=m.get("url"),
                    note=m.get("note"),
                    lms_course_id=_uuid(m.get("lms_course_id")),
                )
                for m in p.get("materials", [])
            ),
            note=note,
            country=p.get("country"),
            location=p.get("location"),
            online=bool(p.get("online", False)),
            acceptance_rate=p.get("acceptance_rate"),
            tuition_usd=p.get("tuition_usd"),
            logo_url=p.get("logo_url"),
            host_institution=p.get("host_institution"),
            duration_weeks=p.get("duration_weeks"),
            ranking=p.get("ranking"),
            org_id=_uuid(p.get("org_id")),
            award_type=p.get("award_type"),
            coverage=tuple(p.get("coverage", [])),
            scope=p.get("scope"),
            amount_text=p.get("amount_text"),
            amount_value=p.get("amount_value"),
            currency=p.get("currency"),
            essay_required=bool(p.get("essay_required", False)),
            eligibility=p.get("eligibility"),
            source_url=p.get("source_url"),
            college_credit=p.get("college_credit"),
            credit_note=p.get("credit_note"),
        )


def _iso(days: Iterable[dt.date]) -> list[str]:
    return [d.isoformat() for d in sorted(set(days))]


def _dates(values: Iterable[str]) -> tuple[dt.date, ...]:
    return tuple(dt.date.fromisoformat(v) for v in values)


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


@dataclass(frozen=True, slots=True)
class Opportunity:
    """A published catalog entry."""

    id: UUID
    draft: OpportunityDraft
    created_by: UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime
    archived: bool = False
    lock_version: int = 0


@dataclass(frozen=True, slots=True)
class OpportunitySubmission:
    """A proposed new entry or edit; `target_id` is set for an edit."""

    id: UUID
    target_id: UUID | None
    payload: dict[str, Any]
    note: str | None
    status: SubmissionStatus
    submitted_by: UUID
    submitter_role: SubmitterRole
    created_at: dt.datetime
    lock_version: int = 0
    reviewed_by: UUID | None = None
    reviewed_at: dt.datetime | None = None
    reason: str | None = None
    applied_id: UUID | None = None

    @property
    def draft(self) -> OpportunityDraft:
        """The proposed entry."""
        return OpportunityDraft.from_payload(self.payload, self.note)


def review_transition(
    current: SubmissionStatus, approve: bool, reason: str | None
) -> SubmissionStatus:
    """Return the next status; only pending moves and a rejection needs a reason."""
    if current != "pending":
        raise ValueError(current)
    if approve:
        return "approved"
    if not (reason or "").strip():
        raise LookupError("reason")
    return "rejected"


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """A catalog entry a student saved, with the grade they aim to do it in."""

    id: UUID
    student_id: UUID
    opportunity_id: UUID
    planned_grade: int | None
    note: str | None
    created_at: dt.datetime


# - - - Recurrence - - -


@dataclass(frozen=True, slots=True)
class Rule:
    """A subset of RFC 5545 RRULE: FREQ, INTERVAL, BYMONTH, BYMONTHDAY, COUNT."""

    freq: Freq
    interval: int = 1
    by_month: tuple[int, ...] = ()
    by_month_day: int | None = None
    count: int | None = None


_FREQS: Final = get_args(Freq)


def _rule_parts(text: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in text.strip().removeprefix("RRULE:").split(";"):
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep or key.upper() in parts:
            raise ValueError(text)
        parts[key.upper()] = value.strip()
    return parts


def _bounded(raw: str, high: int, text: str) -> int | None:
    value = int(raw) if raw else None
    if value is not None and not 1 <= value <= high:
        raise ValueError(text)
    return value


def parse_rule(text: str) -> Rule:
    """Parse `FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=3`; raise ValueError if invalid."""
    parts = _rule_parts(text)
    freq = parts.pop("FREQ", "").upper()
    if freq not in _FREQS:
        raise ValueError(text)
    interval = int(parts.pop("INTERVAL", "1"))
    months = tuple(int(m) for m in parts.pop("BYMONTH", "").split(",") if m)
    day_raw = parts.pop("BYMONTHDAY", "")
    count_raw = parts.pop("COUNT", "")
    if parts or not 1 <= interval <= 52:
        raise ValueError(text)
    if any(not 1 <= m <= 12 for m in months):
        raise ValueError(text)
    day = _bounded(day_raw, 31, text)
    count = _bounded(count_raw, 500, text)
    return Rule(freq, interval, months, day, count)  # type: ignore[arg-type]


def _clamp(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _batch(rule: Rule, start: dt.date, step: int, day: int) -> list[dt.date]:
    if rule.freq == "WEEKLY":
        return [start + dt.timedelta(weeks=step * rule.interval)]
    if rule.freq == "MONTHLY":
        index = start.year * 12 + start.month - 1 + step * rule.interval
        year, month = divmod(index, 12)
        if not rule.by_month or month + 1 in rule.by_month:
            return [_clamp(year, month + 1, day)]
        return []
    year = start.year + step * rule.interval
    months = rule.by_month or (start.month,)
    return [_clamp(year, m, day) for m in sorted(months)]


def occurrences(
    rule: Rule, start: dt.date, after: dt.date, limit: int, until: dt.date | None = None
) -> list[dt.date]:
    """Dates of the rule from `start`, keeping those on or after `after`."""
    out: list[dt.date] = []
    seen = 0
    step = 0
    day = rule.by_month_day or start.day
    while len(out) < limit and step < 2000:
        batch = _batch(rule, start, step, day)
        step += 1
        for d in batch:
            if d < start:
                continue
            if until is not None and d > until:
                return out
            seen += 1
            if rule.count is not None and seen > rule.count:
                return out
            if d >= after:
                out.append(d)
                if len(out) >= limit:
                    return out
    return out


def expected_this_cycle(last_year: Iterable[dt.date], today: dt.date) -> list[dt.date]:
    """Project last year's dates forward by whole years to the next occurrence."""
    out: set[dt.date] = set()
    for d in last_year:
        shifted = _clamp(today.year, d.month, d.day)
        if shifted < today:
            shifted = _clamp(today.year + 1, d.month, d.day)
        out.add(shifted)
    return sorted(out)


DateKind = Literal["registration", "exam", "expected", "recurring"]


@dataclass(frozen=True, slots=True)
class DatedEvent:
    """One upcoming date of an entry; `projected` marks an estimate."""

    day: dt.date
    kind: DateKind
    projected: bool


def upcoming_dates(
    draft: OpportunityDraft, today: dt.date, horizon: dt.date
) -> list[DatedEvent]:
    """Future registration and exam dates, projections when none are announced."""
    events = [
        DatedEvent(d, "registration", False)
        for d in draft.registration_deadlines
        if today <= d <= horizon
    ]
    exams = [d for d in draft.exam_dates if today <= d <= horizon]
    events += [DatedEvent(d, "exam", False) for d in exams]
    if not exams and not draft.recurrence:
        events += [
            DatedEvent(d, "expected", True)
            for d in expected_this_cycle(draft.last_year_dates, today)
            if d <= horizon
        ]
    if draft.recurrence:
        anchors = sorted([*draft.exam_dates, *draft.last_year_dates])
        start = anchors[0] if anchors else today
        events += [
            DatedEvent(d, "recurring", True)
            for d in occurrences(
                parse_rule(draft.recurrence), start, today, MAX_DATES, horizon
            )
            if d not in exams
        ]
    return sorted(events, key=lambda e: (e.day, e.kind))


# - - - Analytics - - -


@dataclass(frozen=True, slots=True)
class PlanAnalytics:
    """Load per grade and term, and coverage of the taxonomy fields."""

    load: dict[str, int] = field(default_factory=dict)
    coverage: dict[UUID, int] = field(default_factory=dict)
    unplaced: int = 0
    conflicts: list[tuple[UUID, UUID, dt.date]] = field(default_factory=list)


def term_of(day: dt.date) -> str:
    """School term of a date: `fall` (Aug–Dec), `spring` (Jan–May), `summer`."""
    if day.month >= 8:
        return "fall"
    if day.month <= 5:
        return "spring"
    return "summer"


def analyse(
    entries: Iterable[PlanEntry],
    catalog: Mapping[UUID, Opportunity],
    field_of: Mapping[UUID, UUID],
    today: dt.date,
    horizon: dt.date,
) -> PlanAnalytics:
    """Count saved items per `grade:term`, per field, and same-day clashes."""
    load: dict[str, int] = {}
    coverage: dict[UUID, int] = {}
    unplaced = 0
    by_day: dict[dt.date, list[UUID]] = {}
    for e in entries:
        opp = catalog.get(e.opportunity_id)
        if opp is None:
            continue
        for fid in {field_of[s] for s in opp.draft.subject_ids if s in field_of}:
            coverage[fid] = coverage.get(fid, 0) + 1
        dates = upcoming_dates(opp.draft, today, horizon)
        main = next((d for d in dates if d.kind != "registration"), None)
        if e.planned_grade is None:
            unplaced += 1
        else:
            term = term_of(main.day) if main else "any"
            key = f"{e.planned_grade}:{term}"
            load[key] = load.get(key, 0) + 1
        for d in dates:
            if d.kind != "registration":
                by_day.setdefault(d.day, []).append(opp.id)
    conflicts = [
        (ids[0], other, day)
        for day, ids in sorted(by_day.items())
        for other in dict.fromkeys(ids[1:])
        if other != ids[0]
    ]
    return PlanAnalytics(load, coverage, unplaced, conflicts)
