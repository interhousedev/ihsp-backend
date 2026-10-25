"""Port to the academic lessons that the reader area needs (adapter in bootstrap)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LessonSubject:
    """What a lesson is about and who attends it."""

    subject_id: UUID
    group_ids: tuple[UUID, ...]
    years_of_study: tuple[int, ...]
    teacher_id: UUID | None


class LessonDirectory(Protocol):
    """Lessons from the academic module."""

    async def get_lesson_subject(self, lesson_id: UUID) -> LessonSubject | None:
        """The subject, groups and year(s) of study of the lesson, or None."""
        ...

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True when the user teaches the lesson."""
        ...

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """True when the active student attends the lesson."""
        ...

    async def earlier_lessons(self, lesson_id: UUID, *, limit: int) -> list[UUID]:
        """Earlier lessons of the same subject and groups, newest first."""
        ...
