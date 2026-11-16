"""Activities, honors and proofs (§2, §3.3)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.profile import ensure_max_chars

ItemKind = Literal["activity", "honor"]
ProofKind = Literal["file", "url", "course"]
ProofStatus = Literal["pending", "verified", "rejected"]

TITLE_MAX: Final = 50
ORG_MAX: Final = 100
DESCRIPTION_MAX: Final = 150
HONOR_DESCRIPTION_MAX: Final = 100
MAX_ACTIVITIES: Final = 10
MAX_HONORS: Final = 5


@dataclass(slots=True)
class Item:
    """One activity or honor, written in Common App limits."""

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

    def validate(self) -> None:
        """Enforce the character limits; normalises text to NFC."""
        self.title = ensure_max_chars(self.title, TITLE_MAX, "title")
        self.organization = ensure_max_chars(self.organization, ORG_MAX, "organization")
        limit = HONOR_DESCRIPTION_MAX if self.kind == "honor" else DESCRIPTION_MAX
        self.description = ensure_max_chars(self.description, limit, "description")


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
