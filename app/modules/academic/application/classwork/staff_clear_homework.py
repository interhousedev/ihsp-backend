"""Use case: remove homework from the staff portal and return the lesson page."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.clear_homework import ClearHomework
from app.modules.academic.application.classwork.staff_lesson import StaffLesson
from app.shared.actor import Actor


class StaffClearHomework:
    """Remove the homework, then show the lesson as the teacher sees it."""

    def __init__(
        self, clear_homework: ClearHomework, staff_lesson: StaffLesson
    ) -> None:
        """Initialize the use case."""
        self.clear_homework = clear_homework
        self.staff_lesson = staff_lesson

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the ``StaffLesson`` JSON after the change."""
        await self.clear_homework.execute(lesson_id, actor)
        return await self.staff_lesson.execute(lesson_id, actor)
