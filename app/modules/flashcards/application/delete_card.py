"""Use case: delete one card; its log rows stay for the heatmap."""

from uuid import UUID

from app.modules.flashcards.domain.errors import CardNotFoundError
from app.modules.flashcards.ports.unit_of_work import UowFactory


class DeleteCard:
    """Deletes a card of the owner's set and keeps `card_count` right."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, *, owner_id: UUID, card_id: UUID) -> None:
        """Delete the card; a card of someone else's set is "not found"."""
        async with self.uow_factory() as uow:
            card = await uow.cards.get(card_id)
            if card is None:
                raise CardNotFoundError()
            flashcard_set = await uow.sets.get_for_update(card.set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise CardNotFoundError()
            await uow.cards.delete_many([card_id])
            flashcard_set.card_count = len(await uow.cards.list_for_set(card.set_id))
            await uow.sets.save(flashcard_set)
            await uow.commit()
