"""Use case: rate a flash card of a block (UF-LMS-03 step 2, LMS-18)."""

from uuid import UUID

from app.modules.lms.application.learning.next_card import (
    require_enrolled,
    study_view,
)
from app.modules.lms.application.learning.revision_loading import (
    find_card_block,
    load_revision,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCardStudyView
from app.modules.lms.domain.learning.cards import (
    counts_as_new,
    counts_as_review,
    state_from_json,
    state_to_json,
)
from app.modules.lms.domain.learning.errors import CardNotFoundError
from app.modules.lms.ports.learning.daily_counters import DailyCounters
from app.shared import srs
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.srs import Rating


class ReviewCard:
    """Apply a rating to one card and return the next card of its block."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, counters: DailyCounters
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.counters = counters

    async def execute(
        self, actor: Actor, step_id: UUID, card_id: str, rating: Rating
    ) -> LearningCardStudyView:
        """Reschedule the card (state per card id) and return the next one.

        Progress is kept per card id, so it survives course updates for cards
        that still exist (LMS-14).
        """
        now = self.clock.now()
        day = local_today(self.clock)
        async with self.uow_factory() as uow:
            context = await require_enrolled(uow, actor, step_id)
            revision = await load_revision(uow, context.live_step.revision_id)
            block = find_card_block(revision.content, card_id)
            if block is None:
                raise CardNotFoundError(params={"card_id": card_id})
            state = await uow.states.get(actor.user_id, step_id)
            states = dict(state.cards) if state else {}
            before = state_from_json(states.get(card_id))
            after = state_to_json(srs.review(before, rating, now))
            await uow.states.save_card(actor.user_id, step_id, card_id, after, now=now)
            await uow.commit()
        new, review = int(counts_as_new(before)), int(counts_as_review(before))
        await self.counters.add(actor.user_id, block.id, day, new=new, review=review)
        usage = await self.counters.get(actor.user_id, block.id, day)
        return study_view(block, {**states, card_id: after}, now, usage)
