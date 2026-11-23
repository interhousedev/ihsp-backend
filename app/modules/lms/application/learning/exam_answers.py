"""Use case: save answers of the open exam module as the student goes."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.exam_session import ExamContext, ExamUseCase
from app.modules.lms.application.learning.views import LearningExamSessionView
from app.modules.lms.domain.learning.errors import ExamModuleClosedError
from app.modules.lms.domain.learning.exam import (
    accepts_answers,
    find_module,
    normalize_module_answers,
)
from app.shared.actor import Actor


class SaveExamAnswers(ExamUseCase):
    """Merge answers into the open module until its deadline plus grace."""

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        module_id: str,
        answers: Mapping[str, Mapping[str, Any]],
    ) -> LearningExamSessionView:
        """Store the answers; a closed or other module raises ExamModuleClosedError.

        The refusal is raised after the transaction is stored, so a module closed
        on the way (its time ran out) stays closed.
        """

        def save(exam: ExamContext, now: datetime) -> bool:
            run = exam.sitting.current if exam.sitting else None
            if run is None or run.module_id != module_id:
                return False
            if not accepts_answers(run, now):
                return False
            module = find_module(exam.block, module_id)[1]
            run.answers = {**run.answers, **normalize_module_answers(module, answers)}
            return True

        view, saved = await self.run(actor, step_id, block_id, save)
        if not saved:
            raise ExamModuleClosedError(params={"module_id": module_id})
        return view
