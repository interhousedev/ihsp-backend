"""In-memory `LessonDirectory` for the library tests."""

from uuid import UUID

from app.modules.library.ports.lesson_directory import LessonSubject
from app.shared.ids import new_id


class FakeLessonDirectory:
    """Lessons configured by the test: `add()` returns the lesson id."""

    def __init__(self) -> None:
        """Start without lessons."""
        self.lessons: dict[UUID, LessonSubject] = {}
        self.students: dict[UUID, set[UUID]] = {}  # lesson -> students
        self.history: dict[UUID, list[UUID]] = {}  # lesson -> earlier, newest first

    def add(
        self,
        subject_id: UUID,
        *,
        teacher_id: UUID | None = None,
        students: tuple[UUID, ...] = (),
        years: tuple[int, ...] = (1,),
        earlier: list[UUID] | None = None,
    ) -> UUID:
        """Register a lesson of the subject with its teacher and attending students."""
        lesson_id = new_id()
        self.lessons[lesson_id] = LessonSubject(
            subject_id=subject_id,
            group_ids=(new_id(),),
            years_of_study=years,
            teacher_id=teacher_id,
        )
        self.students[lesson_id] = set(students)
        self.history[lesson_id] = list(earlier or [])
        return lesson_id

    async def get_lesson_subject(self, lesson_id: UUID) -> LessonSubject | None:
        """The configured lesson or None."""
        return self.lessons.get(lesson_id)

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True for the configured teacher."""
        lesson = self.lessons.get(lesson_id)
        return lesson is not None and lesson.teacher_id == user_id

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True for the configured students."""
        return user_id in self.students.get(lesson_id, set())

    async def earlier_lessons(self, lesson_id: UUID, *, limit: int) -> list[UUID]:
        """The configured earlier lessons, newest first."""
        return self.history.get(lesson_id, [])[:limit]
