"""Activities, honors and proofs (§2, §3.3)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.profile import ensure_max_chars

ItemKind = Literal["activity", "honor"]
ItemStatus = Literal["draft", "ready"]
ProofKind = Literal["file", "url", "course"]
ProofStatus = Literal["pending", "verified", "rejected"]

TITLE_MAX: Final = 50
ORG_MAX: Final = 100
DESCRIPTION_MAX: Final = 150
HONOR_DESCRIPTION_MAX: Final = 100
MAX_ACTIVITIES: Final = 10
MAX_HONORS: Final = 5
MAX_DRAFTS: Final = 30
POST_GRAD: Final = 13
"""Grade level 13 stands for post-graduate year."""
GRADES: Final = (9, 10, 11, 12, POST_GRAD)
TIMINGS: Final = ("school_year", "school_break", "all_year")
RECOGNITION_LEVELS: Final = ("school", "state_regional", "national", "international")
MAX_HOURS_PER_WEEK: Final = 168
MAX_WEEKS_PER_YEAR: Final = 52
# Common App activity types; an activity's `category` holds one of them, an
# honor's `category` holds one of RECOGNITION_LEVELS.
ACTIVITY_TYPES: Final = (
    "Academic",
    "Art",
    "Athletics: Club",
    "Athletics: JV/Varsity",
    "Career-Oriented",
    "Community Service (Volunteer)",
    "Computer/Technology",
    "Cultural",
    "Dance",
    "Debate/Speech",
    "Environmental",
    "Family Responsibilities",
    "Foreign Exchange",
    "Journalism/Publication",
    "Junior R.O.T.C.",
    "LGBT",
    "Music: Instrumental",
    "Music: Vocal",
    "Religious",
    "Research",
    "Robotics",
    "School Spirit",
    "Science/Math",
    "Social Justice",
    "Student Govt./Politics",
    "Theater/Drama",
    "Work (Paid)",
    "Other Club/Activity",
)


@dataclass(slots=True)
class Item:
    """One activity or honor, written in Common App limits.

    `title` is the Common App position/leadership (activities) or honor title.
    Drafts may be incomplete; `ready` items satisfy `missing_for_ready`.
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

    def validate(self) -> None:
        """Enforce the character limits; normalises text to NFC."""
        self.title = ensure_max_chars(self.title, TITLE_MAX, "title")
        self.organization = ensure_max_chars(self.organization, ORG_MAX, "organization")
        limit = HONOR_DESCRIPTION_MAX if self.kind == "honor" else DESCRIPTION_MAX
        self.description = ensure_max_chars(self.description, limit, "description")

    def missing_for_ready(self) -> list[str]:
        """Return the field names that block `ready` (empty when complete)."""
        missing: list[str] = []
        if not self.title.strip():
            missing.append("title")
        if self.kind == "honor":
            if self.category not in RECOGNITION_LEVELS:
                missing.append("category")
            missing.extend(self._missing_grades())
            return missing
        if self.category not in ACTIVITY_TYPES:
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
