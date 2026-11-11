"""Use case: the student reads their own homework submission."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    TodoUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
from app.modules.academic.application.classwork.submission_views import (
    SubmissionViewBuilder,
)
from app.modules.academic.domain.classwork.errors import (
    LessonNotFoundError,
    SubmissionNotFoundError,
)
from app.shared.actor import Actor


class GetHomeworkSubmission:
    """Return the caller's submission for a lesson."""

    def __init__(
        self,
        uow_factory: Callable[[], TodoUnitOfWork],
        views: SubmissionViewBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(self, lesson_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the ``HomeworkSubmission`` JSON or raise a not-found error."""
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            lesson = await uow.lesson_reader.visible_lesson(keys_of(student), lesson_id)
            if lesson is None:
                raise LessonNotFoundError(params={"lesson_id": str(lesson_id)})
            record = await uow.submissions.get(student.user_id, lesson_id)
        if record is None:
            raise SubmissionNotFoundError(params={"lesson_id": str(lesson_id)})
        return await self.views.student_view(record, lesson.homework_due_date)
