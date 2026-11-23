"""Use case: submit the open exam module; the last one finishes the exam."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.exam_session import ExamContext, ExamUseCase
from app.modules.lms.application.learning.views import LearningExamSessionView
from app.modules.lms.domain.learning.exam import (
    accepts_answers,
    close_run,
    find_module,
)
from app.shared.actor import Actor


class SubmitExamModule(ExamUseCase):
    """Close and grade the module; repeating it returns the same sitting.

    A module whose time and grace ran out is already closed as late by then; a
    submission within the grace counts at its own time, never after the deadline.
    """

    async def execute(
        self, actor: Actor, step_id: UUID, block_id: str, module_id: str
    ) -> LearningExamSessionView:
        """Submit the module and return the sitting (with the result at the end)."""

        def submit(exam: ExamContext, now: datetime) -> None:
            run = exam.sitting.current if exam.sitting else None
            if run is None or run.module_id != module_id:
                return
            if accepts_answers(run, now):
                module = find_module(exam.block, module_id)[1]
                close_run(run, module, min(now, run.deadline_at), late=False)

        view, _ = await self.run(actor, step_id, block_id, submit)
        return view
