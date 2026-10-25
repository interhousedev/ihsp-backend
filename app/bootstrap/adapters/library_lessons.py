"""Adapter: the library's `LessonDirectory` over the academic schedule queries."""

import datetime as dt
import re
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.library.ports.lesson_directory import LessonSubject
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries

HISTORY_WINDOW = dt.timedelta(days=150)
GROUP_YEAR = re.compile(r"^\s*(\d)")


class LibraryLessonsAdapter:
    """Subject, groups and history of lessons for book plans and lesson links."""

    def __init__(self, queries: ScheduleQueries, clock: Clock) -> None:
        """Store the schedule queries and the clock."""
        self.queries = queries
        self.clock = clock

    async def get_lesson_subject(self, lesson_id: UUID) -> LessonSubject | None:
        """The subject, groups and year(s) of study of the lesson, or None."""
        lesson = await self.queries.get_lesson(lesson_id)
        if lesson is None:
            return None
        years = sorted(
            {
                int(match.group(1))
                for name in lesson.group_names
                if (match := GROUP_YEAR.match(name))
            }
        )
        return LessonSubject(
            subject_id=lesson.subject_id,
            group_ids=tuple(sorted(audience_keys.group_ids(lesson.audience), key=str)),
            years_of_study=tuple(years),
            teacher_id=lesson.teacher_id,
        )

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True when the user teaches the lesson."""
        return await self.queries.is_lesson_teacher(user_id, lesson_id)

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True when the active student attends the lesson."""
        return await self.queries.is_in_audience(user_id, lesson_id)

    async def earlier_lessons(self, lesson_id: UUID, *, limit: int) -> list[UUID]:
        """Earlier lessons of the same subject and audience, newest first."""
        lesson = await self.queries.get_lesson(lesson_id)
        if lesson is None or lesson.teacher_id is None:
            return []
        today = local_today(self.clock)
        found = await self.queries.lessons_for_teacher(
            lesson.teacher_id, lesson.date - HISTORY_WINDOW, today
        )
        earlier = [
            other
            for other in found
            if other.id != lesson_id
            and other.subject_id == lesson.subject_id
            and set(other.audience) == set(lesson.audience)
            and (other.date, other.period) < (lesson.date, lesson.period)
        ]
        earlier.sort(key=lambda other: (other.date, other.period), reverse=True)
        return [other.id for other in earlier[:limit]]
