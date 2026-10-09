"""List the published collections for any reader (LIB-4)."""

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.views import CollectionView
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class ListCollections:
    """`GET /v1/library/collections` (anonymous allowed)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        builder: CollectionBuilder,
    ) -> None:
        """Store the unit of work factory, the user directory and the helpers."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.builder = builder

    async def execute(
        self, viewer: Actor | None, *, accept_language: str | None = None
    ) -> list[CollectionView]:
        """Published collections by position; counts include only visible items."""
        locale = await resolve_locale(self.identity, viewer, accept_language)
        async with self.uow_factory() as uow:
            collections = await uow.taxonomy.collections(published_only=True)
            stored = await uow.taxonomy.collection_item_ids([c.id for c in collections])
            every_id = list(dict.fromkeys(i for ids in stored.values() for i in ids))
            visible = {
                item.id for item in await self.builder.visible_items(uow, every_id, viewer)
            }
        return [
            await self.builder.public_view(
                collection,
                sum(1 for i in stored.get(collection.id, []) if i in visible),
                locale,
            )
            for collection in collections
        ]
