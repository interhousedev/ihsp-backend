"""Use case: store the score of an H5P block from the player's xAPI statement."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningBlockResultView
from app.modules.lms.domain.learning.block_results import (
    map_xapi,
    merge_h5p,
    result_key,
    stored_result,
)
from app.modules.lms.domain.learning.errors import H5PNotFoundError
from app.modules.lms.domain.step_content import H5PBlock
from app.shared.actor import Actor
from app.shared.clock import Clock


class RecordH5PResult:
    """Keep the best score and sticky completion of the block in the step state.

    Statements that do not describe the whole content (sub-questions, progress
    verbs) change nothing; the current result is returned either way.
    """

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, completion: StepCompletion
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.completion = completion

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        statement: Mapping[str, Any],
    ) -> LearningBlockResultView:
        """Map the statement and store it when it is a result of the content."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id)
            revision = await load_revision(uow, context.live_step.revision_id)
            block = next(
                (
                    b
                    for b in revision.content.blocks
                    if isinstance(b, H5PBlock) and b.id == block_id
                ),
                None,
            )
            if block is None:
                raise H5PNotFoundError(params={"block_id": block_id})
            state = await uow.states.get(actor.user_id, step_id)
            previous = stored_result(state.cards if state else {}, block_id)
            record = dict(previous or {})
            result = map_xapi(statement)
            if result is not None:
                record = merge_h5p(previous, result, block.passing_score_pct)
                await uow.states.save_card(
                    actor.user_id, step_id, result_key(block_id), record, now=now
                )
                await self.completion.after_block_result(
                    uow, actor.user_id, step_id, now
                )
            await uow.commit()
        return LearningBlockResultView(
            score=float(record.get("score", 0)),
            max_score=float(record.get("max_score", 0)),
            completed=bool(record.get("completed")),
        )
