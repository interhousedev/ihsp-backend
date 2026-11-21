"""Activities, honors and proofs (§2, §3.3)."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.errors import InvalidAnswerError
from app.modules.admission.domain.profile import ensure_max_chars
from app.shared.honor_categories import HONOR_CATEGORIES

ItemKind = Literal["activity", "honor"]
ItemStatus = Literal["draft", "ready"]
ProofKind = Literal["file", "url", "course"]
ProofStatus = Literal["pending", "verified", "rejected"]

TITLE_MAX: Final = 60
"""Common App allows 50; 60 leaves room for the student to trim."""
ORG_MAX: Final = 110
DESCRIPTION_MAX: Final = 600
TITLE_WARN: Final = 50
"""Soft limit: longer titles are allowed but flagged."""
ORG_WARN: Final = 100
DESCRIPTION_WARN: Final = 150
MAX_ACTIVITIES: Final = 10
MAX_HONORS: Final = 5
MAX_DRAFTS: Final = 30
POST_GRAD: Final = 13
"""Grade level 13 stands for post-graduate year."""
GRADES: Final = (9, 10, 11, 12, POST_GRAD)
TIMINGS: Final = ("school_year", "school_break", "all_year")
RECOGNITION_LEVELS: Final = ("school", "regional", "national", "international")
MAX_HOURS_PER_WEEK: Final = 168
MAX_WEEKS_PER_YEAR: Final = 52
# An activity's `category` holds one of ACTIVITY_CATEGORIES; an honor's `category` holds
# one of HONOR_CATEGORIES (shared with certificate types) and its `level` one of
# RECOGNITION_LEVELS.
ACTIVITY_CATEGORIES: Final = (
    "academic",
    "arts",
    "athletics",
    "leadership_service",
    "cultural_global",
    "stem_research",
    "other",
)
GRADE_LETTERS: Final = ("A", "B", "C", "D", "E")
GRADE_TIP_MAX: Final = 160


@dataclass(frozen=True, slots=True)
class ItemGrade:
    """The AI grade of an item's title and description (A best, E weakest).

    `content_hash` keys the cache: the grade is current while the graded text
    hashes to it.
    """

    content_hash: str
    locale: str
    title_grade: str
    title_tip: str
    description_grade: str
    description_tip: str
    model: str


def grade_content_hash(item: "Item", locale: str) -> str:
    """Return the cache key of a grade: the text the model sees, and the language."""
    raw = "\x1f".join(
        (
            "item-grade@1",
            locale,
            item.kind,
            item.category or "",
            item.level or "",
            item.title.strip(),
            item.organization.strip(),
            item.description.strip(),
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(slots=True)
class Item:
    """One activity or honor, written in Common App limits.

    `title` is the Common App position/leadership (activities) or honor title.
    Drafts and ready items may be incomplete (`ready` needs a title);
    `missing_for_ready` lists what the student should still fill in.
    """

    id: UUID
    student_id: UUID
    kind: ItemKind
    title: str
    organization: str = ""
    description: str = ""
    category: str | None = None
    grades: tuple[int, ...] = ()
    hours_per_week: int | None = None
    weeks_per_year: int | None = None
    position: int = 0
    starred: bool = False
    created_at: datetime | None = None
    lock_version: int = 0
    status: ItemStatus = "draft"
    timing: tuple[str, ...] = ()
    intend_in_college: bool | None = None
    grade: ItemGrade | None = None
    level: str | None = None
    """Honors only: one of RECOGNITION_LEVELS."""
    certificate_entry_id: UUID | None = None
    """Honors only: the platform certificate this honor was made from."""

    @property
    def grade_stale(self) -> bool:
        """True when the stored grade was made for other text than the item has."""
        g = self.grade
        return g is not None and grade_content_hash(self, g.locale) != g.content_hash

    def validate(self) -> None:
        """Enforce the character limits; normalises text to NFC."""
        self.title = ensure_max_chars(self.title, TITLE_MAX, "title")
        self.organization = ensure_max_chars(self.organization, ORG_MAX, "organization")
        self.description = ensure_max_chars(
            self.description, DESCRIPTION_MAX, "description"
        )
        allowed = HONOR_CATEGORIES if self.kind == "honor" else ACTIVITY_CATEGORIES
        if self.category is not None and self.category not in allowed:
            raise InvalidAnswerError(params={"question": "category"})
        if self.level is not None and (
            self.kind != "honor" or self.level not in RECOGNITION_LEVELS
        ):
            raise InvalidAnswerError(params={"question": "level"})
        if self.certificate_entry_id is not None and self.kind != "honor":
            raise InvalidAnswerError(params={"question": "certificate_entry_id"})
        if not set(self.grades) <= set(GRADES):
            raise InvalidAnswerError(params={"question": "grades"})
        for name, value, top in (
            ("hours_per_week", self.hours_per_week, MAX_HOURS_PER_WEEK),
            ("weeks_per_year", self.weeks_per_year, MAX_WEEKS_PER_YEAR),
        ):
            if value is not None and not 0 <= value <= top:
                raise InvalidAnswerError(params={"question": name})

    def missing_for_ready(self) -> list[str]:
        """Return the field names that block `ready` (empty when complete)."""
        missing: list[str] = []
        if not self.title.strip():
            missing.append("title")
        if self.kind == "honor":
            if self.category not in HONOR_CATEGORIES:
                missing.append("category")
            if self.level not in RECOGNITION_LEVELS:
                missing.append("level")
            missing.extend(self._missing_grades())
            return missing
        if self.category not in ACTIVITY_CATEGORIES:
            missing.append("category")
        if not self.organization.strip():
            missing.append("organization")
        if not self.description.strip():
            missing.append("description")
        missing.extend(self._missing_grades())
        missing.extend(self._missing_activity_schedule())
        return missing

    def _missing_grades(self) -> list[str]:
        """Return ["grades"] when the grades are absent or out of range."""
        if not self.grades or not set(self.grades) <= set(GRADES):
            return ["grades"]
        return []

    def _missing_activity_schedule(self) -> list[str]:
        """Return the unset timing and commitment fields of an activity."""
        missing: list[str] = []
        if not self.timing or not set(self.timing) <= set(TIMINGS):
            missing.append("timing")
        if self.hours_per_week is None:
            missing.append("hours_per_week")
        if self.weeks_per_year is None:
            missing.append("weeks_per_year")
        if self.intend_in_college is None:
            missing.append("intend_in_college")
        return missing


@dataclass(frozen=True, slots=True)
class Proof:
    """Evidence attached to an item."""

    id: UUID
    item_id: UUID
    kind: ProofKind
    file_id: UUID | None = None
    url: str | None = None
    course_id: UUID | None = None
    status: ProofStatus = "pending"


def allowed_proof_url(url: str) -> bool:
    """Return whether a proof URL is an https URL with a host (SSRF-safe shape)."""
    parts = urlsplit(url.strip())
    return parts.scheme == "https" and bool(parts.hostname) and parts.username is None
