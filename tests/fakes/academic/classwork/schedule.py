"""Fake schedule queries: the parts classwork consumes."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.shared.contracts.academic import LessonRef, RoomRef, StudentRef


class FakeSchedule:
    """In-memory ScheduleQueries with settable curators, heads and projections."""

    def __init__(self) -> None:
        """Start empty."""
        self.students: dict[UUID, StudentRef] = {}
        self.curated: dict[UUID, list[UUID]] = {}
        self.heads: dict[UUID, list[UUID]] = {}
        self.projected: list[LessonRef] = []

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return the student record or None."""
        return self.students.get(user_id)

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Not used by classwork."""
        return None

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Not used by classwork."""
        return []

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Not used by classwork."""
        return []

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Not used by classwork."""
        return False

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Not used by classwork."""
        return False

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return the configured heads of the lesson's groups."""
        return list(self.heads.get(lesson_id, []))

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Not used by classwork."""
        return None

    async def room_day(self, room_id: UUID, day: dt.date) -> list[LessonRef]:
        """Not used by classwork."""
        return []

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Not used by classwork."""
        return []

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int
    ) -> list[LessonRef]:
        """Not used by classwork."""
        return []

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return the groups the teacher curates."""
        return list(self.curated.get(teacher_id, []))

    async def projected_lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the configured projected lessons inside the range."""
        return [lesson for lesson in self.projected if start <= lesson.date <= end]
