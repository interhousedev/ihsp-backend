"""Use case: put an item on the shelf or move it between states (LIB-7)."""

from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.reader.access import load_visible_item
from app.modules.library.application.reader.shelf_view import shelf_entry_view
from app.modules.library.application.reader.views import ShelfEntryView
from app.modules.library.domain.enums import ShelfState
from app.modules.library.domain.reader_shelf import place_on_shelf
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class PutShelfEntry:
    """Shelve a book, a material or a pinned UniLibrary record (as a link)."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock, cards: CardBuilder) -> None:
        """Store the unit of work factory, the clock and the card builder."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cards = cards

    async def execute(
        self, actor: Actor, item_id: UUID, state: ShelfState, *, locale: str
    ) -> ShelfEntryView:
        """Set the state of the item on the actor's shelf and return the entry."""
        async with self.uow_factory() as uow:
            item = await load_visible_item(uow, actor, item_id)
            current = await uow.shelf.get(actor.user_id, item_id)
            entry = place_on_shelf(
                current,
                user_id=actor.user_id,
                item_id=item_id,
                state=state,
                now=self.clock.now(),
            )
            if entry is not current:
                await uow.shelf.save(entry)
            [card] = await self.cards.build(uow, [item], viewer=actor, locale=locale)
            await uow.commit()
        return shelf_entry_view(entry, item, card, actor)
