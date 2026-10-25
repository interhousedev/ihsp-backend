"""Use case: answer a question of an interactive video block."""

from uuid import UUID

from app.modules.lms.application.learning.next_card import require_enrolled
from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_completion import StepCompletion
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningBlockResultView,
    LearningInteractionAnswerView,
    LearningInteractionResultView,
)
from app.modules.lms.domain.learning.block_results import (
    record_answer,
    result_key,
    stored_result,
)
from app.modules.lms.domain.learning.errors import (
    BlockNotFoundError,
    InteractionNotFoundError,
)
from app.modules.lms.domain.step_content import InteractiveVideoBlock
from app.shared.actor import Actor
from app.shared.clock import Clock


class AnswerInteraction:
    """Grade the answer against the live revision and keep it in the step state."""

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
        interaction_id: str,
        option_ids: list[str],
    ) -> LearningInteractionResultView:
        """Return whether the answer is right and the block's result so far.

        Only the first answer to a question counts; repeating it returns the
        stored answer.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id)
            revision = await load_revision(uow, context.live_step.revision_id)
            block = next(
                (
                    b
                    for b in revision.content.blocks
                    if isinstance(b, InteractiveVideoBlock) and b.id == block_id
                ),
                None,
            )
            if block is None:
                raise BlockNotFoundError(params={"block_id": block_id})
            state = await uow.states.get(actor.user_id, step_id)
            previous = stored_result(state.cards if state else {}, block_id)
            try:
                record = record_answer(block, previous, interaction_id, option_ids)
            except KeyError as exc:
                raise InteractionNotFoundError(
                    params={"interaction_id": interaction_id}
                ) from exc
            await uow.states.save_card(
                actor.user_id, step_id, result_key(block_id), record, now=now
            )
            await self.completion.after_block_result(uow, actor.user_id, step_id, now)
            await uow.commit()
        correct = {
            option.id
            for interaction in block.interactions
            if interaction.id == interaction_id
            for option in interaction.options
            if option.correct
        }
        return LearningInteractionResultView(
            answer=LearningInteractionAnswerView(**record["answers"][interaction_id]),
            correct_option_ids=sorted(correct),
            result=LearningBlockResultView(
                score=float(record["score"]),
                max_score=float(record["max_score"]),
                completed=bool(record["completed"]),
            ),
        )
