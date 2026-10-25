"""Use case: the next card to study in a set (WEB-23, UF-WEB-22)."""

from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import StudyNextView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.ports.unit_of_work import UowFactory


class StudyNext:
    """Picks the card: due learning cards, then reviews, then new cards."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(self, *, owner_id: UUID, set_id: UUID) -> StudyNextView:
        """Return the card with the button labels, or `done_for_today`."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            cards = await uow.cards.list_for_set(set_id)
        return await self.views.study(flashcard_set, cards)
