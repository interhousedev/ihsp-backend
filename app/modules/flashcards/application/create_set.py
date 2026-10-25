"""Use case: create a flash card set (WEB-22)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.flashcard import fresh_card
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.domain.validation import (
    check_card_count,
    clean_description,
    clean_title,
)
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateSet:
    """Creates a set with its cards, all in the state `new`."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, views: SetViews
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.views = views

    async def execute(
        self,
        *,
        owner_id: UUID,
        title: str,
        cards: Sequence[tuple[str, str]],
        source: SetSource,
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> SetDetailView:
        """Check title and cards (at most 500, 1-2000 characters), then save."""
        check_card_count(len(cards))
        flashcard_set = FlashcardSet(
            id=new_id(),
            owner_id=owner_id,
            title=clean_title(title),
            created_at=self.clock.now(),
            source=source,
            description=clean_description(description),
            source_chat_id=source_chat_id,
            card_count=len(cards),
        )
        built = [
            fresh_card(flashcard_set.id, position, front, back)
            for position, (front, back) in enumerate(cards)
        ]
        async with self.uow_factory() as uow:
            await uow.sets.add(flashcard_set)
            await uow.cards.add_many(built)
            await uow.commit()
        return await self.views.detail(flashcard_set, built)
