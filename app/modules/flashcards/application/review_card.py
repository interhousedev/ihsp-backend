"""Use case: rate a card and get the next one (WEB-23, UF-WEB-22)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import StudyNextView
from app.modules.flashcards.domain.errors import CardNotFoundError
from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.review_log import ReviewLogEntry, clamp_duration
from app.modules.flashcards.domain.study import study_day
from app.modules.flashcards.ports.daily_counters import CounterKind, DailyCounters
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating

_COUNTED: dict[CardState, CounterKind] = {
    CardState.NEW: "new",
    CardState.REVIEW: "review",
}


class ReviewCard:
    """Applies the rating to the card and counts it against today's limits."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        counters: DailyCounters,
        views: SetViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.counters = counters
        self.views = views

    async def execute(
        self,
        *,
        owner_id: UUID,
        card_id: UUID,
        rating: Rating,
        duration_ms: int | None = None,
    ) -> StudyNextView:
        """Save the new state and a log row; count the answer against today's limits.

        A first answer counts as a new card and an answer on a review card as a
        review. `duration_ms` is the time the student looked at the card.
        """
        now = self.clock.now()
        async with self.uow_factory() as uow:
            card = await uow.cards.get_for_update(card_id)
            flashcard_set = await uow.sets.get(card.set_id) if card else None
            if card is None or flashcard_set is None:
                raise CardNotFoundError()
            if not flashcard_set.owned_by(owner_id):
                raise CardNotFoundError()
            before = card.answer(rating, now)
            await uow.cards.save(card)
            await uow.reviews.add(
                _log_entry(owner_id, card, rating, before, now, duration_ms)
            )
            await uow.commit()
            cards = await uow.cards.list_for_set(flashcard_set.id)
        kind = _COUNTED.get(before)
        if kind is not None:
            await self.counters.increment(
                owner_id, flashcard_set.id, study_day(now), kind
            )
        return await self.views.study(flashcard_set, cards)


def _log_entry(
    owner_id: UUID,
    card: Flashcard,
    rating: Rating,
    before: CardState,
    now: datetime,
    duration_ms: int | None,
) -> ReviewLogEntry:
    delay = (card.due_at or now) - now
    return ReviewLogEntry(
        id=new_id(),
        user_id=owner_id,
        set_id=card.set_id,
        card_id=card.id,
        rating=rating,
        state_before=before,
        interval_after_days=delay / timedelta(days=1),
        reviewed_at=now,
        duration_ms=clamp_duration(duration_ms),
    )
