"""Use case: attempts, correct and incorrect answers and last study time per card.

Built from the review log, so practice answers count and only answers logged since
the log exists are known. Again is incorrect; any other button is correct.
"""

from uuid import UUID

from app.modules.flashcards.application.views import CardStatsView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.review_log import CardAttempts
from app.modules.flashcards.ports.unit_of_work import UowFactory


class GetCardStats:
    """One row per current card, in the order of the set."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, *, owner_id: UUID, set_id: UUID
    ) -> tuple[CardStatsView, ...]:
        """Return the rows; someone else's set is "not found"."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            cards = await uow.cards.list_for_set(set_id)
            attempts = await uow.reviews.card_attempts(owner_id, set_id=set_id)
        rows = []
        for card in cards:
            found = attempts.get(card.id, CardAttempts())
            rows.append(
                CardStatsView(
                    card_id=card.id,
                    front=card.front,
                    hardness=card.hardness.value,
                    attempts=found.attempts,
                    correct=found.correct,
                    incorrect=found.incorrect,
                    last_studied_at=found.last_studied_at,
                )
            )
        return tuple(rows)
