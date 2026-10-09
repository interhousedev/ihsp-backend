"""ClassworkQueries.subject_lessons and TermCalendar for the notebooks tests."""

import datetime as dt
from uuid import UUID

from app.shared.contracts.academic import LessonRef
from tests.fakes.notebooks.schedule import FakeLessonSchedule


class FakeClasswork:
    """The lessons of a subject that a student attends, read from the schedule fake."""

    def __init__(self, schedule: FakeLessonSchedule) -> None:
        """Share the lessons and audience of the schedule fake."""
        self.schedule = schedule

    async def subject_lessons(
        self,
        user_id: UUID,
        subject_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[LessonRef]:
        """Return the student's lessons of the subject inside the window."""
        return [
            lesson
            for lesson in self.schedule.lessons
            if lesson.subject_id == subject_id
            and (user_id, lesson.id) in self.schedule.audience
            and (start is None or lesson.date >= start)
            and (end is None or lesson.date <= end)
        ]


class FakeTermCalendar:
    """The current term; `window` is None for a calendar without terms."""

    def __init__(self) -> None:
        """Start with a term around the default test day."""
        self.window: tuple[dt.date, dt.date] | None = (
            dt.date(2026, 9, 1),
            dt.date(2026, 12, 31),
        )

    async def current_term_dates(
        self, today: dt.date
    ) -> tuple[dt.date, dt.date] | None:
        """Return the configured window."""
        return self.window
