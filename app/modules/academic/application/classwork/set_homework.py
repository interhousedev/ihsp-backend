"""Use case: the teacher sets a lesson's homework (ACA-10, UF-STF-05)."""

import datetime as dt
from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import HomeworkCancelledLessonError
from app.modules.academic.domain.classwork.homework_rules import clean_homework_text
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor
from app.shared.clock import Clock


class SetHomework:
    """Save text and due date; the due date follows the next lesson unless set."""

    def __init__(
        self, uow_factory: Callable[[], LessonUnitOfWork], clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        lesson_id: UUID,
        actor: Actor,
        text: str,
        due_date: dt.date | None,
    ) -> Lesson:
        """Save the homework and return the updated lesson."""
        clean = clean_homework_text(text)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            if not lesson.scheduled:
                raise HomeworkCancelledLessonError(params={"lesson_id": str(lesson_id)})
            due = due_date
            if due is None:
                due = await uow.lessons.next_lesson_date(
                    subject_id=lesson.subject_id,
                    audience=lesson.audience,
                    after=lesson.date,
                )
            await uow.lessons.set_homework(
                lesson_id,
                text=clean,
                due_date=due,
                due_auto=due_date is None,
                by=actor.user_id,
                at=self.clock.now(),
                mark_updated=lesson.has_homework and lesson.homework_text != clean,
            )
            await uow.commit()
            return await require_lesson(uow, lesson_id)
