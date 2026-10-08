"""Use case: edit the text of one card; its progress is kept (WEB-24)."""

from uuid import UUID

from app.modules.flashcards.application.set_views import card_view
from app.modules.flashcards.application.views import CardView
from app.modules.flashcards.domain.errors import CardNotFoundError
from app.modules.flashcards.domain.validation import check_card_text
from app.modules.flashcards.ports.unit_of_work import UowFactory


class UpdateCard:
    """Changes the front, the back or both."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, *, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> CardView:
        """Save the new text; a card of someone else's set is "not found"."""
        async with self.uow_factory() as uow:
            card = await uow.cards.get_for_update(card_id)
            flashcard_set = await uow.sets.get(card.set_id) if card else None
            if card is None or flashcard_set is None:
                raise CardNotFoundError()
            if not flashcard_set.owned_by(owner_id):
                raise CardNotFoundError()
            new_front = card.front if front is None else front
            new_back = card.back if back is None else back
            check_card_text(new_front, new_back)
            card.front, card.back = new_front, new_back
            await uow.cards.save(card)
            await uow.commit()
        return card_view(card)
