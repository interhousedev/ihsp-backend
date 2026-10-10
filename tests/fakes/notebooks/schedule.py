"""ScheduleQueries: audience, get_lesson and get_student for the notebooks tests."""

import datetime as dt
from uuid import UUID

from app.shared.contracts.academic import LessonRef, StudentRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import FakeSchedule


class FakeLessonSchedule(FakeSchedule):
    """Lessons with an audience of students."""

    def __init__(self) -> None:
        """Start with no students; every student gets one group on demand."""
        super().__init__()
        self.group_id = new_id()

    def attend(self, user_id: UUID, lesson: LessonRef) -> LessonRef:
        """Register the lesson and put the student in its audience."""
        if lesson not in self.lessons:
            self.lessons.append(lesson)
        self.audience.add((user_id, lesson.id))
        return lesson

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """The lessons the student attends between two dates."""
        return [
            lesson
            for lesson in self.lessons
            if (user_id, lesson.id) in self.audience and start <= lesson.date <= end
        ]

    async def get_lesson(self, lesson_id: UUID) -> LessonRef | None:
        """Return the lesson."""
        return next((x for x in self.lessons if x.id == lesson_id), None)

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Every student is in the same group, without a subgroup."""
        return StudentRef(
            user_id=user_id,
            group_id=self.group_id,
            group_name="2TN2",
            subgroup=None,
            status="active",
            synced_at=None,
        )
