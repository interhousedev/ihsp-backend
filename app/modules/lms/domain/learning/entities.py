"""Entities of the learning side of the LMS (plain data, no framework)."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.modules.lms.domain.learning.live import LiveManifest
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.domain.step_content import StepContent

Visibility = Literal["public", "invite"]


@dataclass(frozen=True, slots=True)
class LearningCourse:
    """The live values of a course (drafts are not visible here)."""

    id: UUID
    slug: str
    title: str
    description: str
    cover_file_id: UUID | None
    visibility: str
    invite_code: str | None
    status: str
    live_version_id: UUID | None
    updated_at: datetime | None = None

    @property
    def is_open_for_students(self) -> bool:
        """Return True when the course is published and not archived."""
        return self.live_version_id is not None and self.status == "active"


@dataclass(frozen=True, slots=True)
class LiveVersion:
    """A published version: its manifest and when it went live."""

    id: UUID
    course_id: UUID
    number: int
    manifest: LiveManifest
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StaffMember:
    """A course staff member with permissions."""

    user_id: UUID
    role: str
    permissions: frozenset[str]
    show_on_page: bool
    position: int


@dataclass(frozen=True, slots=True)
class LearningStep:
    """The stable identity of a step."""

    id: UUID
    course_id: UUID


@dataclass(frozen=True, slots=True)
class RevisionData:
    """A frozen revision of a step with its parsed content."""

    id: UUID
    step_id: UUID
    kind: str
    content: StepContent


@dataclass(slots=True)
class Enrollment:
    """A user's enrollment in a course (LMS-19)."""

    id: UUID
    course_id: UUID
    user_id: UUID
    via: str
    completed_at: datetime | None = None
    progress_pct: int = 0
    progress_version_id: UUID | None = None
    last_seen_version_id: UUID | None = None


@dataclass(slots=True)
class StepState:
    """A student's progress in one step; cards hold the SRS state per card id."""

    user_id: UUID
    step_id: UUID
    viewed_at: datetime
    completed_at: datetime | None = None
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class Attempt:
    """One attempt at a test block, graded on the revision the student saw."""

    id: UUID
    user_id: UUID
    step_id: UUID
    revision_id: UUID
    block_id: str
    attempt_no: int
    is_preview: bool
    variant: Variant
    started_at: datetime
    deadline_at: datetime | None
    max_score: Decimal
    submitted_at: datetime | None = None
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    score: Decimal | None = None
    passed: bool | None = None
    override_score: Decimal | None = None
    override_comment: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None

    @property
    def is_submitted(self) -> bool:
        """Return True once the attempt has a result."""
        return self.submitted_at is not None

    @property
    def effective_score(self) -> Decimal | None:
        """Return the reviewer's score if there is one, else the graded score."""
        return self.override_score if self.override_score is not None else self.score

    def is_expired(self, now: datetime) -> bool:
        """Return True if the time limit is over and the attempt is not submitted."""
        return (
            self.submitted_at is None
            and self.deadline_at is not None
            and now >= self.deadline_at
        )
