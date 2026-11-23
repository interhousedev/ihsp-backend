"""Port: the engagement repository and its unit of work (XP, review, quests)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.domain.engagement.fsrs import FsrsState
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork


@dataclass(frozen=True, slots=True)
class XpRecord:
    """One row of the XP ledger."""

    source: str
    ref: str
    xp: int
    at: datetime


@dataclass(frozen=True, slots=True)
class SubmittedAttempt:
    """A submitted, non-preview test attempt (input of the XP sync)."""

    id: UUID
    step_id: UUID
    revision_id: UUID
    block_id: str
    variant: dict[str, Any]
    answers: dict[str, Any]
    score: Decimal | None
    max_score: Decimal
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReviewItem:
    """A missed question with its FSRS state."""

    id: UUID
    user_id: UUID
    course_id: UUID
    step_id: UUID
    revision_id: UUID
    block_id: str
    question_id: str
    state: FsrsState


@dataclass(frozen=True, slots=True)
class QuestRecord:
    """A class quest row."""

    id: UUID
    course_id: UUID
    title: str
    goal_kind: str
    target: int
    class_target: int
    starts_on: date
    ends_on: date


class EngagementRepository(Protocol):
    """Engagement reads and writes inside the learning transaction."""

    async def profile(self, user_id: UUID) -> tuple[int, datetime | None]:
        """Return the weekly goal and the XP sync watermark."""
        ...

    async def mark_synced(self, user_id: UUID, at: datetime) -> None:
        """Store the XP sync watermark."""
        ...

    async def attempts_since(
        self, user_id: UUID, since: datetime | None
    ) -> list[SubmittedAttempt]:
        """Return the user's submitted non-preview attempts after `since`."""
        ...

    async def completions_since(
        self, user_id: UUID, since: datetime | None
    ) -> list[tuple[UUID, datetime]]:
        """Return (step_id, completed_at) of steps completed after `since`."""
        ...

    async def scores_before(
        self, user_id: UUID, step_id: UUID, block_id: str, before: datetime
    ) -> list[tuple[Decimal | None, Decimal]]:
        """Return (score, max_score) of earlier submitted non-preview attempts."""
        ...

    async def course_of_steps(self, step_ids: Sequence[UUID]) -> dict[UUID, UUID]:
        """Return the course id of each step."""
        ...

    async def add_xp(
        self,
        user_id: UUID,
        course_id: UUID | None,
        source: str,
        ref: str,
        xp: int,
        earned_on: date,
    ) -> bool:
        """Record an award once per (user, source, ref); True when new."""
        ...

    async def xp_total(self, user_id: UUID) -> int:
        """Return the user's total XP."""
        ...

    async def active_days(self, user_id: UUID, since: date) -> list[date]:
        """Return the days with any XP from `since`."""
        ...

    async def recent_xp(self, user_id: UUID, limit: int) -> list[XpRecord]:
        """Return the newest XP awards."""
        ...

    async def reviews_on(self, user_id: UUID, day: date) -> int:
        """Return how many review answers earned XP on a day."""
        ...

    async def xp_on(self, user_id: UUID, day: date, source: str) -> int:
        """Return the XP of one source earned on a day."""
        ...

    async def course_progress(
        self, course_id: UUID, kind: str, start: date, end: date
    ) -> dict[UUID, int]:
        """Return each enrolled learner's progress on a quest metric."""
        ...

    async def add_review_item(
        self,
        *,
        user_id: UUID,
        course_id: UUID,
        step_id: UUID,
        revision_id: UUID,
        block_id: str,
        question_id: str,
        state: FsrsState,
    ) -> None:
        """Queue a missed question unless it is already queued."""
        ...

    async def due_items(
        self, user_id: UUID, now: datetime, limit: int, step_ids: Sequence[UUID]
    ) -> list[StoredReviewItem]:
        """Return the user's due questions in the given steps, oldest due first."""
        ...

    async def due_count(
        self, user_id: UUID, now: datetime, step_ids: Sequence[UUID]
    ) -> int:
        """Return how many questions in the given steps are due."""
        ...

    async def due_counts(self, now: datetime) -> dict[UUID, int]:
        """Return the number of due questions per user."""
        ...

    async def get_item(self, item_id: UUID) -> StoredReviewItem | None:
        """Return a review item."""
        ...

    async def save_item(self, item_id: UUID, state: FsrsState) -> None:
        """Store the new FSRS state."""
        ...

    async def unlock_threshold(self, course_id: UUID) -> int | None:
        """Return the mastery unlock threshold of a course."""
        ...

    async def set_unlock_threshold(self, course_id: UUID, pct: int | None) -> None:
        """Store the mastery unlock threshold."""
        ...

    async def quests_of(
        self, course_ids: Sequence[UUID], active_on: date | None = None
    ) -> list[QuestRecord]:
        """Return the quests of courses, optionally only those running on a day."""
        ...

    async def quests_of_all_active(self, day: date) -> list[QuestRecord]:
        """Return every quest running on a day."""
        ...

    async def get_quest(self, quest_id: UUID) -> QuestRecord | None:
        """Return a quest."""
        ...

    async def save_quest(self, quest: QuestRecord, created_by: UUID) -> None:
        """Insert or update a quest."""
        ...

    async def delete_quest(self, quest_id: UUID) -> None:
        """Delete a quest."""
        ...

    async def learners_with_recent_xp(self, since: date) -> list[UUID]:
        """Return the users with any XP since a day."""
        ...


class EngagementUnitOfWork(LearningUnitOfWork, Protocol):
    """The learning transaction with the engagement repository."""

    @property
    def engagement(self) -> EngagementRepository:
        """XP, review items, settings and quests."""
        ...
