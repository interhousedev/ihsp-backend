"""Use case: copy a shared flash card set to my sets (SHR-5)."""

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import ShareNotFoundError
from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.ports.share_resolver import ShareResolver
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id

SHARED_SET_KIND = "flashcard_set"


class CopyFromShare:
    """Copies the cards of a shared set into a new set with fresh progress."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        links: ShareResolver,
        views: SetViews,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.links = links
        self.views = views

    async def execute(self, *, actor: Actor, share_slug: str) -> SetDetailView:
        """Copy the set behind an active share; its cards start as `new`."""
        resolved = await self.links.resolve_share(share_slug)
        if resolved is None or resolved[0] != SHARED_SET_KIND:
            raise ShareNotFoundError()
        async with self.uow_factory() as uow:
            original = await uow.sets.get(resolved[1])
            if original is None:
                raise ShareNotFoundError()
            originals = await uow.cards.list_for_set(original.id)
            copy = FlashcardSet(
                id=new_id(),
                owner_id=actor.user_id,
                title=original.title,
                created_at=self.clock.now(),
                source=SetSource.COPIED,
                description=original.description,
                copied_from_set_id=original.id,
                card_count=len(originals),
            )
            cards = [
                Flashcard(new_id(), copy.id, position, card.front, card.back)
                for position, card in enumerate(originals)
            ]
            await uow.sets.add(copy)
            await uow.cards.add_many(cards)
            await uow.commit()
        return await self.views.detail(copy, cards)
