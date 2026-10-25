"""Port: read models over lessons for views, lists and reminders."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import HomeworkRecord


class LessonReader(Protocol):
    """Queries that return lessons with names resolved."""

    async def audience_lessons(
        self,
        keys: Sequence[str],
        start: dt.date,
        end: dt.date,
        *,
        subject_id: UUID | None = None,
    ) -> list[Lesson]:
        """Lessons of any status whose audience matches the keys, by date."""
        ...

    async def teacher_lessons(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[Lesson]:
        """The teacher's lessons of any status between two dates."""
        ...

    async def visible_lesson(
        self, keys: Sequence[str], lesson_id: UUID
    ) -> Lesson | None:
        """The lesson if its audience matches the keys."""
        ...

    async def next_study_day(
        self, keys: Sequence[str], after: dt.date
    ) -> dt.date | None:
        """Earliest date after ``after`` with a scheduled lesson for the keys."""
        ...

    async def first_scheduled_on(
        self, keys: Sequence[str], day: dt.date
    ) -> Lesson | None:
        """The first scheduled lesson of a day for the keys."""
        ...

    async def homework_records(
        self, student_id: UUID, keys: Sequence[str], since: dt.date
    ) -> list[HomeworkRecord]:
        """Scheduled lessons with homework from a date on, with the to-do state."""
        ...

    async def student_absences(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> list[tuple[Lesson, bool]]:
        """Lessons the student missed and whether each absence is excused."""
        ...

    async def missing_attendance(
        self,
        teacher_id: UUID | None,
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> list[Lesson]:
        """Finished scheduled lessons with a teacher and no submitted attendance."""
        ...

    async def starting_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[Lesson]:
        """Scheduled lessons starting in ``(start, end]``."""
        ...

    async def ending_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[Lesson]:
        """Scheduled lessons ending in ``(start, end]``."""
        ...
