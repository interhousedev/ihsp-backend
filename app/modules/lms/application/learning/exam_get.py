"""Use case: my sitting of an exam block (closes a module whose time ran out)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.exam_session import ExamContext, ExamUseCase
from app.modules.lms.application.learning.views import LearningExamSessionView
from app.shared.actor import Actor


class GetExamSession(ExamUseCase):
    """Return the sitting; an expired module is closed with its saved answers."""

    async def execute(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> LearningExamSessionView:
        """Return the sitting as its owner may see it now."""
        view, _ = await self.run(actor, step_id, block_id, _nothing)
        return view


def _nothing(exam: ExamContext, now: datetime) -> None:
    """Change nothing."""
