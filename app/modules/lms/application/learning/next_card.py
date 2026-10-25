"""Use case: the next flash card of a block (UF-LMS-03 step 2, LMS-18)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import (
    find_flashcards_block,
    load_revision,
)
from app.modules.lms.application.learning.step_context import (
    StepContext,
    load_live_step,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningCardCountsView,
    LearningCardIntervalsView,
    LearningCardStudyView,
    LearningCardView,
)
from app.modules.lms.domain.learning.cards import (
    DailyUsage,
    intervals_for,
    select_next,
    state_from_json,
)
from app.modules.lms.domain.learning.errors import NotEnrolledError
from app.modules.lms.domain.step_content import FlashcardsBlock
from app.modules.lms.ports.learning.daily_counters import DailyCounters
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


def study_view(
    block: FlashcardsBlock,
    states: Mapping[str, Mapping[str, Any]],
    now: datetime,
    usage: DailyUsage,
) -> LearningCardStudyView:
    """Return the card to study now with its button intervals and today's counts."""
    card_id, counts = select_next([c.id for c in block.cards], states, now, usage)
    card = next((c for c in block.cards if c.id == card_id), None)
    return LearningCardStudyView(
        block_id=block.id,
        card=(
            None
            if card is None
            else LearningCardView(id=card.id, front=card.front, back=card.back)
        ),
        intervals=(
            None
            if card is None
            else LearningCardIntervalsView(
                **intervals_for(state_from_json(states.get(card.id)), now)
            )
        ),
        counts=LearningCardCountsView(
            learning=counts.learning, review=counts.review, new=counts.new
        ),
    )


async def require_enrolled(
    uow: LearningUnitOfWork, actor: Actor, step_id: UUID
) -> StepContext:
    """Return the live step context; flash cards are for enrolled students only."""
    context = await load_live_step(uow, step_id)
    if await uow.enrollments.get(context.course.id, actor.user_id) is None:
        raise NotEnrolledError(params={"course_id": str(context.course.id)})
    return context


class NextCard:
    """Pick the next card by the Anki-like order and the daily limits."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, counters: DailyCounters
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.counters = counters

    async def execute(
        self, actor: Actor, step_id: UUID, block_id: str
    ) -> LearningCardStudyView:
        """Return the next card of the block, or none when nothing is due."""
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id)
            revision = await load_revision(uow, context.live_step.revision_id)
            block = find_flashcards_block(revision.content, block_id)
            state = await uow.states.get(actor.user_id, step_id)
        usage = await self.counters.get(
            actor.user_id, block_id, local_today(self.clock)
        )
        return study_view(block, state.cards if state else {}, self.clock.now(), usage)
