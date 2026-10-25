"""Use case: change a set's title, description and daily limits (WEB-23, WEB-24)."""

from enum import Enum
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.validation import (
    check_new_per_day,
    check_reviews_per_day,
    clean_description,
    clean_title,
)
from app.modules.flashcards.ports.unit_of_work import UowFactory


class Unset(Enum):
    """Marks a field the client did not send (None clears the description)."""

    UNSET = "unset"


UNSET = Unset.UNSET


class UpdateSet:
    """Edits the fields that were sent and leaves the others alone."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self,
        *,
        owner_id: UUID,
        set_id: UUID,
        title: str | None = None,
        description: str | None | Unset = UNSET,
        new_per_day: int | None = None,
        reviews_per_day: int | None = None,
    ) -> SetDetailView:
        """Validate and save; limits are 1-200 new and 1-2000 reviews per day."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get_for_update(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            if title is not None:
                flashcard_set.title = clean_title(title)
            if not isinstance(description, Unset):
                flashcard_set.description = clean_description(description)
            if new_per_day is not None:
                flashcard_set.new_per_day = check_new_per_day(new_per_day)
            if reviews_per_day is not None:
                flashcard_set.reviews_per_day = check_reviews_per_day(reviews_per_day)
            await uow.sets.save(flashcard_set)
            await uow.commit()
            cards = await uow.cards.list_for_set(set_id)
        return await self.views.detail(flashcard_set, cards)
