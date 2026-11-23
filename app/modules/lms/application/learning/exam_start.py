"""Use case: begin the next module of an exam (or resume the open one)."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.application.learning.exam_session import ExamContext, ExamUseCase
from app.modules.lms.application.learning.views import LearningExamSessionView
from app.modules.lms.domain.learning.exam import ExamSitting, next_module, start_run
from app.shared.actor import Actor


class StartExamModule(ExamUseCase):
    """Open the next module with a server-side deadline; idempotent while open.

    The first call creates the sitting on the live revision. A finished sitting
    is returned unchanged: an exam is taken once.
    """

    async def execute(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> LearningExamSessionView:
        """Start the next module and return the sitting with its questions."""
        view, _ = await self.run(actor, step_id, block_id, _start)
        return view


def _start(exam: ExamContext, now: datetime) -> None:
    """Open the next module unless one is open or the exam is over."""
    sitting = exam.sitting
    if sitting is not None and (
        sitting.finished_at is not None or sitting.current is not None
    ):
        return
    following = next_module(exam.block, sitting.runs if sitting else [])
    if following is None:
        return
    if sitting is None:
        sitting = ExamSitting(revision_id="", started_at=now, runs=[])
        exam.sitting = sitting
    sitting.runs.append(start_run(*following, now))
