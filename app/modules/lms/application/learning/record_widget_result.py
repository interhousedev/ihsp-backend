"""Use case: store the score a graded code or HTML widget reports from the browser.

Code runs and HTML widgets execute only in the learner's browser (a sandboxed
frame), so the score is self-reported: it is bounded to 0..100, the block must be
a graded widget of the live step, and only the enrolled student's own state is
written. The best score is kept and a pass is sticky, like H5P. The result is
stored as not verified: the pass completes the block, but it earns no points,
so it never adds to a certificate score, a badge score rule or XP beyond the
completion of the step.
"""

from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningBlockResultView
from app.modules.lms.domain.learning.block_results import (
    merge_widget,
    result_key,
    stored_result,
)
from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    CourseNotFoundError,
)
from app.modules.lms.domain.step_content import CodeBlock, HtmlBlock
from app.shared.actor import Actor
from app.shared.clock import Clock


class RecordWidgetResult:
    """Keep the best score and sticky pass of a graded code or HTML block."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        completion: StepCompletion,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.completion = completion
        self.gate = gate

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        block_id: str,
        score_pct: float,
        passed: bool,
    ) -> LearningBlockResultView:
        """Merge the reported result into the student's step state."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id, self.gate)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            revision = await load_revision(uow, context.live_step.revision_id)
            block = next(
                (
                    b
                    for b in revision.content.blocks
                    if isinstance(b, CodeBlock | HtmlBlock)
                    and b.id == block_id
                    and b.graded
                ),
                None,
            )
            if block is None:
                raise BlockNotFoundError(params={"block_id": block_id})
            state = await uow.states.get(actor.user_id, step_id)
            previous = stored_result(state.cards if state else {}, block_id)
            record = merge_widget(previous, score_pct, passed)
            await uow.states.save_card(
                actor.user_id, step_id, result_key(block_id), record, now=now
            )
            await self.completion.after_block_result(uow, actor.user_id, step_id, now)
            await uow.commit()
        return LearningBlockResultView(
            score=float(record["score"]),
            max_score=float(record["max_score"]),
            completed=bool(record["passed"]),
            verified=False,
        )
