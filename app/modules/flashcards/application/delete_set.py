"""Use case: delete a set with its cards."""

from uuid import UUID

from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.ports.unit_of_work import UowFactory


class DeleteSet:
    """Deletes the owner's set."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, *, owner_id: UUID, set_id: UUID) -> None:
        """Delete the set; someone else's set is "not found"."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get_for_update(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            await uow.sets.delete(set_id)
            await uow.commit()
