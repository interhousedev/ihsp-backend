"""Use case: study a finished set again today.

How the schedule is treated: the restart is a practice round beside the schedule.
Its answers never change a card's state, due date, ease, interval or last review,
and never touch the daily counters, so a restart cannot shorten or stretch an
interval and cannot use up tomorrow's limits. Cards above today's new-card limit
take part but stay new. The answers go to the review log with `practice = true`:
they count as attempts in the statistics and as study in the heatmap. The round
lives in Redis under today's date, so it ends by itself at midnight.
"""

from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import StudyNextView
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    StudyNotFinishedError,
)
from app.modules.flashcards.domain.study import practice_order, study_day
from app.modules.flashcards.ports.practice_rounds import PracticeRounds
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class RestartStudy:
    """Starts a practice round over every card of the set."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        practice: PracticeRounds,
        views: SetViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.practice = practice
        self.views = views

    async def execute(self, *, owner_id: UUID, set_id: UUID) -> StudyNextView:
        """Return the first card of the round; refuse while scheduled cards wait."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            cards = await uow.cards.list_for_set(set_id)
        current = await self.views.study(flashcard_set, cards)
        if current.card is not None and not current.practice:
            raise StudyNotFinishedError()
        now = self.clock.now()
        order = practice_order(
            cards, shuffle=flashcard_set.shuffle, salt=now.isoformat()
        )
        await self.practice.start(
            owner_id, set_id, study_day(now), [card.id for card in order]
        )
        return await self.views.study(flashcard_set, cards)
