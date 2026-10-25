"""List every collection with all languages, for the librarian (LIB-2)."""

from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.views import ManageCollectionView
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class ListManageCollections:
    """`GET /v1/manage/library/collections`: published or not."""

    def __init__(self, *, uow_factory: UowFactory, builder: CollectionBuilder) -> None:
        """Store the unit of work factory and the collection helpers."""
        self.uow_factory = uow_factory
        self.builder = builder

    async def execute(self, actor: Actor) -> list[ManageCollectionView]:
        """All collections by position, each with its stored item ids."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            collections = await uow.taxonomy.collections(published_only=False)
            items = await uow.taxonomy.collection_item_ids([c.id for c in collections])
        return [
            await self.builder.manage_view(c, items.get(c.id, [])) for c in collections
        ]
