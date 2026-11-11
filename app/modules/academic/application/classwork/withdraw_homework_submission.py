"""Use case: the student withdraws their homework submission."""

from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.classwork.ports.unit_of_work import (
    TodoUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import require_student
from app.modules.academic.domain.classwork.errors import SubmissionNotFoundError
from app.shared.actor import Actor


class WithdrawHomeworkSubmission:
    """Delete the caller's own submission; the files stay in their storage."""

    def __init__(self, uow_factory: Callable[[], TodoUnitOfWork]) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, lesson_id: UUID, actor: Actor) -> None:
        """Remove the submission or raise a not-found error."""
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            if not await uow.submissions.delete(student.user_id, lesson_id):
                raise SubmissionNotFoundError(params={"lesson_id": str(lesson_id)})
            await uow.commit()
