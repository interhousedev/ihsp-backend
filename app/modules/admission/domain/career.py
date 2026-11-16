"""Career exploration: an inventory, professions, majors and minors, one spike.

The inventory questions and the majors taxonomy are rows that administrators edit;
the code keeps only the shape and the limits. A student's answers, shortlist, choice
of majors and minors and the confirmed spike live in one plan per student.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import CharLimitError, InvalidAnswerError

CareerSection = Literal["interests", "values", "skills"]
SECTIONS: Final[tuple[CareerSection, ...]] = ("interests", "values", "skills")
LOCALES: Final = ("uz", "ru", "en")

PROMPT_MAX: Final = 300
"""Characters of one localized question or major name."""
CODE_MAX: Final = 48
AREA_MAX: Final = 48
ANSWER_MAX: Final = 600
PROFESSIONS_MAX: Final = 8
"""Professions the model suggests at most."""
SHORTLIST_MAX: Final = 5
MAJORS_MAX: Final = 3
MINORS_MAX: Final = 2
TITLE_MAX: Final = 120
REASON_MAX: Final = 400
SUMMARY_MAX: Final = 800
EVIDENCE_MAX: Final = 6
GAPS_MAX: Final = 5


def localized(texts: dict[str, str], locale: str) -> str:
    """The text in the locale, falling back to English, then any text."""
    return texts.get(locale) or texts.get("en") or next(iter(texts.values()), "")


def check_localized(field_name: str, texts: dict[str, str]) -> dict[str, str]:
    """Return the three locales trimmed; reject a missing or over-long one."""
    out: dict[str, str] = {}
    for locale in LOCALES:
        value = (texts.get(locale) or "").strip()
        if not value or len(value) > PROMPT_MAX:
            raise CharLimitError(
                params={
                    "field": f"{field_name}.{locale}",
                    "limit": PROMPT_MAX,
                    "count": len(value),
                }
            )
        out[locale] = value
    return out


def check_text(field_name: str, value: str, limit: int) -> str:
    """Return the trimmed text; reject an empty or over-long one."""
    clean = value.strip()
    if not clean or len(clean) > limit:
        raise CharLimitError(
            params={"field": field_name, "limit": limit, "count": len(clean)}
        )
    return clean


@dataclass(slots=True)
class CareerQuestion:
    """One inventory question with its text in every locale."""

    id: UUID
    section: CareerSection
    prompt: dict[str, str]
    sort_order: int = 0
    active: bool = True

    def validate(self) -> None:
        """Check the section and the texts."""
        if self.section not in SECTIONS:
            raise InvalidAnswerError(params={"question": "section"})
        self.prompt = check_localized("prompt", self.prompt)


@dataclass(slots=True)
class CareerMajor:
    """A major (and maybe a minor) of the taxonomy, grouped by area."""

    id: UUID
    code: str
    area: str
    name: dict[str, str]
    minor_ok: bool = True
    sort_order: int = 0
    active: bool = True

    def validate(self) -> None:
        """Check the code, the area and the names."""
        self.code = check_text("code", self.code, CODE_MAX).lower()
        self.area = check_text("area", self.area, AREA_MAX)
        self.name = check_localized("name", self.name)


@dataclass(frozen=True, slots=True)
class Profession:
    """A suggested profession; the student shortlists a few."""

    title: str
    reason: str
    shortlisted: bool = False


@dataclass(frozen=True, slots=True)
class MajorFit:
    """How well a major of the taxonomy fits the student (0 to 100)."""

    code: str
    score: int
    reason: str


@dataclass(frozen=True, slots=True)
class SpikeEvidence:
    """An activity or honor that shows the spike."""

    item_id: UUID
    note: str


@dataclass(frozen=True, slots=True)
class Spike:
    """The one thing the application is known for, with evidence and gaps."""

    title: str
    summary: str
    evidence: tuple[SpikeEvidence, ...] = ()
    gaps: tuple[str, ...] = ()
    confirmed_at: datetime | None = None


@dataclass(slots=True)
class CareerPlan:
    """A student's career exploration so far."""

    student_id: UUID
    answers: dict[str, str] = field(default_factory=dict)
    professions: list[Profession] = field(default_factory=list)
    majors: list[str] = field(default_factory=list)
    minors: list[str] = field(default_factory=list)
    fit: list[MajorFit] = field(default_factory=list)
    spike: Spike | None = None
    lock_version: int = 0

    @property
    def shortlist(self) -> list[Profession]:
        """The shortlisted professions."""
        return [p for p in self.professions if p.shortlisted]


def clean_answers(answers: dict[str, str], known: set[str]) -> dict[str, str]:
    """Keep answers to known questions, trimmed; empty answers are dropped."""
    out: dict[str, str] = {}
    for key, value in answers.items():
        if key not in known:
            raise InvalidAnswerError(params={"question": key})
        text = value.strip()
        if len(text) > ANSWER_MAX:
            raise CharLimitError(
                params={"field": "answer", "limit": ANSWER_MAX, "count": len(text)}
            )
        if text:
            out[key] = text
    return out


def choose_majors(
    majors: list[str], minors: list[str], taxonomy: dict[str, CareerMajor]
) -> tuple[list[str], list[str]]:
    """Validate a choice: known active codes, minors allowed, no overlap, caps."""
    majors = list(dict.fromkeys(majors))
    minors = list(dict.fromkeys(minors))
    if len(majors) > MAJORS_MAX or len(minors) > MINORS_MAX:
        raise InvalidAnswerError(params={"question": "majors"})
    for code in majors:
        if code not in taxonomy or not taxonomy[code].active:
            raise InvalidAnswerError(params={"question": "majors"})
    for code in minors:
        major = taxonomy.get(code)
        if major is None or not major.active or not major.minor_ok or code in majors:
            raise InvalidAnswerError(params={"question": "minors"})
    return majors, minors
