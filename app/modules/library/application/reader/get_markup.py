"""Use case: the actor's own page markup of an item."""

from uuid import UUID

from app.modules.library.application.reader.access import load_readable_item
from app.modules.library.domain.reader_markup import Markup
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetMarkup:
    """Read the markup of the item; nobody else's is ever returned."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, item_id: UUID) -> Markup | None:
        """The actor's markup, or None when there is none (404 for a closed item)."""
        async with self.uow_factory() as uow:
            await load_readable_item(uow, actor, item_id)
            return await uow.markup.get(actor.user_id, item_id)
