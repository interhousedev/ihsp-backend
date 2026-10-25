"""Use case: append cards to a set (AI and MCP clients, WEB-24)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.flashcard import fresh_card
from app.modules.flashcards.domain.validation import check_card_count, check_card_text
from app.modules.flashcards.ports.unit_of_work import UowFactory


class AddCards:
    """Adds new cards after the last one."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self, *, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> SetDetailView:
        """Add (front, back) pairs; the set may not grow past 500 cards."""
        for front, back in cards:
            check_card_text(front, back)
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get_for_update(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            existing = await uow.cards.list_for_set(set_id)
            check_card_count(len(existing) + len(cards))
            start = max((card.position for card in existing), default=-1) + 1
            added = [
                fresh_card(set_id, start + offset, front, back)
                for offset, (front, back) in enumerate(cards)
            ]
            await uow.cards.add_many(added)
            flashcard_set.card_count = len(existing) + len(added)
            await uow.sets.save(flashcard_set)
            await uow.commit()
        return await self.views.detail(flashcard_set, [*existing, *added])
