"""Port: course badges, their awards and the learner facts that earn them."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.domain.badge_model import Badge
from app.modules.lms.domain.badges import BadgeDesign, BadgeRule, LearnerFacts


@dataclass(frozen=True, slots=True)
class StoredBadge:
    """A badge as stored: its design, rule, switch and order."""

    id: UUID
    course_id: UUID
    design: BadgeDesign
    rule: BadgeRule
    enabled: bool
    position: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredAward:
    """A badge a learner earned."""

    id: UUID
    badge_id: UUID
    user_id: UUID
    course_id: UUID | None
    awarded_at: datetime
    seen_at: datetime | None


class BadgeRepository(Protocol):
    """Badges of courses and awards of learners."""

    async def for_course(self, course_id: UUID) -> list[StoredBadge]:
        """Return the badges of a course in display order."""
        ...

    async def for_courses(self, course_ids: Sequence[UUID]) -> list[StoredBadge]:
        """Return the badges of several courses in display order."""
        ...

    async def get(self, badge_id: UUID) -> StoredBadge | None:
        """Return one badge."""
        ...

    async def count(self, course_id: UUID) -> int:
        """Return how many badges a course has."""
        ...

    async def add(
        self,
        course_id: UUID,
        design: BadgeDesign,
        rule: BadgeRule,
        enabled: bool,
        created_by: UUID,
    ) -> UUID:
        """Store a new badge at the end of the list."""
        ...

    async def update(
        self, badge_id: UUID, design: BadgeDesign, rule: BadgeRule, enabled: bool
    ) -> None:
        """Replace the design, rule and switch of a badge."""
        ...

    async def delete(self, badge_id: UUID) -> None:
        """Remove a badge and its awards."""
        ...

    async def show_locked(self, course_id: UUID) -> bool:
        """Return whether learners see badges they have not earned."""
        ...

    async def set_show_locked(self, course_id: UUID, value: bool) -> None:
        """Store whether learners see badges they have not earned."""
        ...

    async def award_counts(self, course_id: UUID) -> dict[UUID, int]:
        """Return how many learners earned each badge of a course."""
        ...

    async def awards_of(self, user_id: UUID) -> list[StoredAward]:
        """Return every badge a learner earned, newest first."""
        ...

    async def get_award(self, award_id: UUID) -> StoredAward | None:
        """Return one award."""
        ...

    async def award(
        self, badge_id: UUID, user_id: UUID, course_id: UUID | None, at: datetime
    ) -> bool:
        """Store an award once; return False when it already existed."""
        ...

    async def mark_seen(self, award_id: UUID, now: datetime) -> None:
        """Record that the learner saw the celebration of an award."""
        ...

    async def facts(
        self,
        user_id: UUID,
        course_id: UUID,
        sections: Sequence[tuple[str, Sequence[UUID]]],
        completed_at: datetime | None,
        today: date,
    ) -> LearnerFacts | None:
        """Return the learner facts of an enrolled learner, else None."""
        ...


class BadgeStore(Protocol):
    """Badges as whole aggregates (course and platform), outside a learning unit."""

    async def add(self, badge: Badge) -> None:
        """Store a new badge."""
        ...

    async def get(self, id: UUID) -> Badge | None:
        """Return one badge."""
        ...

    async def update(self, badge: Badge) -> None:
        """Replace a stored badge."""
        ...

    async def count_for_course(self, course_id: UUID) -> int:
        """Return how many badges a course has."""
        ...


class EnrolmentFacts(Protocol):
    """Pages the learner facts of the enrolments of one course."""

    async def total(self, course_id: UUID) -> int:
        """Return the exact number of enrolments."""
        ...

    async def page(
        self, course_id: UUID, cursor: int | None, limit: int
    ) -> tuple[list[tuple[UUID, LearnerFacts]], int | None]:
        """Return up to `limit` learners from `cursor` and the next cursor."""
        ...


class PlatformFactsReader(Protocol):
    """Pages the platform-wide facts of every active user."""

    async def page(
        self, cursor: int | None, limit: int
    ) -> tuple[list[tuple[UUID, Any]], int | None]:
        """Return (user id, facts with level, coach_resolved, courses_completed)."""
        ...


class AwardStore(Protocol):
    """Writes an award and its `lms.badge_awarded` event in one transaction."""

    async def award(
        self, badge_id: UUID, user_id: UUID, at: datetime, event: dict[str, Any]
    ) -> bool:
        """Return False and write nothing when the award exists."""
        ...


class BackfillQueue(Protocol):
    """Schedules one batch of a badge backfill."""

    async def enqueue(self, badge_id: UUID, cursor: int | None = None) -> None:
        """Queue the batch starting at `cursor`."""
        ...


class BadgeCourseAccess(Protocol):
    """Staff `edit` of one course."""

    async def require_edit(self, actor: Any, course_id: UUID) -> None:  # noqa: ANN401
        """Raise ForbiddenError unless the actor may edit the course."""
        ...
