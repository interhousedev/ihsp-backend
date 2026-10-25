"""Use case: set homework from the staff portal and return the lesson page."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.set_homework import SetHomework
from app.modules.academic.application.classwork.staff_lesson import StaffLesson
from app.shared.actor import Actor


class StaffSetHomework:
    """Save the homework, then show the lesson as the teacher sees it."""

    def __init__(self, set_homework: SetHomework, staff_lesson: StaffLesson) -> None:
        """Initialize the use case."""
        self.set_homework = set_homework
        self.staff_lesson = staff_lesson

    async def execute(
        self, lesson_id: UUID, actor: Actor, text: str, due_date: dt.date | None
    ) -> dict[str, Any]:
        """Return the ``StaffLesson`` JSON after the change."""
        await self.set_homework.execute(lesson_id, actor, text, due_date)
        return await self.staff_lesson.execute(lesson_id, actor)
