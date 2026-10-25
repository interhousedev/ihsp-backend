"""Use case: take an item off the shelf (LIB-7)."""

from uuid import UUID

from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class RemoveShelfEntry:
    """Remove an entry; removing one that is not there is harmless."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, item_id: UUID) -> None:
        """Delete the actor's entry for the item."""
        async with self.uow_factory() as uow:
            await uow.shelf.remove(actor.user_id, item_id)
            await uow.commit()
