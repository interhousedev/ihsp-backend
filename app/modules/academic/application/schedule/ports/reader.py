"""Read-side port: joined queries for the public API and lists."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.shared.contracts.academic import RoomRef, StudentRef


@dataclass(frozen=True, slots=True)
class LessonFilters:
    """Filters of the admin lesson list."""

    start: dt.date | None = None
    end: dt.date | None = None
    group_id: UUID | None = None
    teacher_id: UUID | None = None
    room_id: UUID | None = None
    status: str | None = None
    teacher_needed: bool | None = None


@dataclass(frozen=True, slots=True)
class LessonPage:
    """A page of lesson views with the keyset cursor of the next page."""

    items: list[LessonView]
    next_cursor: dict[str, Any] | None


class ScheduleReader(Protocol):
    """Queries that join lessons with subjects, rooms and groups."""

    async def student_ref(self, user_id: UUID) -> StudentRef | None:
        """Return the student with the group name."""
        ...

    async def lesson_view(self, lesson_id: UUID, locale: str) -> LessonView | None:
        """Return one lesson."""
        ...

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the student's lessons (any status) between two dates."""
        ...

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the teacher's lessons (any status) between two dates."""
        ...

    async def projected_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return generated lessons plus lessons projected from entries."""
        ...

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the active student attends the lesson."""
        ...

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the user is the lesson's teacher."""
        ...

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return head students of the groups in the lesson's audience."""
        ...

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room with the slug."""
        ...

    async def room_day(
        self, room_id: UUID, day: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the room's lessons on a day ordered by period."""
        ...

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int]
    ) -> list[UUID]:
        """Return user ids of the groups' active students."""
        ...

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int, locale: str
    ) -> list[LessonView]:
        """Search the user's lessons by subject, topic or homework."""
        ...

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return the active groups the teacher curates."""
        ...

    async def list_lessons(
        self,
        filters: LessonFilters,
        *,
        cursor: dict[str, Any] | None,
        limit: int,
        locale: str,
    ) -> LessonPage:
        """Return a page of lessons ordered by date, period and id."""
        ...
