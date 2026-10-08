"""Use case: open one of the owner's sets with its cards."""

from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.ports.unit_of_work import UowFactory


class GetSet:
    """Returns a set to its owner; someone else's set is "not found"."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(self, *, owner_id: UUID, set_id: UUID) -> SetDetailView:
        """Return the set with all its cards."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            cards = await uow.cards.list_for_set(set_id)
        return await self.views.detail(flashcard_set, cards)
