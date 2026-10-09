"""Open one published collection with its item cards (LIB-4)."""

from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.views import CollectionDetailView
from app.modules.library.domain.errors import CollectionNotFoundError
from app.modules.library.domain.taxonomy_collections import Collection
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetCollection:
    """`GET /v1/library/collections/{id}` (anonymous allowed; id or slug)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        cards: CardBuilder,
        builder: CollectionBuilder,
    ) -> None:
        """Store the unit of work factory, the directory and the card helpers."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.cards = cards
        self.builder = builder

    async def execute(
        self,
        viewer: Actor | None,
        id_or_slug: str,
        *,
        accept_language: str | None = None,
    ) -> CollectionDetailView:
        """The collection and the cards of the items the viewer may see.

        An unpublished collection is not found, whoever asks.
        """
        locale = await resolve_locale(self.identity, viewer, accept_language)
        async with self.uow_factory() as uow:
            collection = await self._find(uow, id_or_slug)
            if collection is None or not collection.published:
                raise CollectionNotFoundError(params={"collection": id_or_slug})
            stored = await uow.taxonomy.collection_item_ids([collection.id])
            items = await self.builder.visible_items(
                uow, stored.get(collection.id, []), viewer
            )
            cards = await self.cards.build(uow, items, viewer=viewer, locale=locale)
        return CollectionDetailView(
            collection=await self.builder.public_view(collection, len(cards), locale),
            items=tuple(cards),
        )

    @staticmethod
    async def _find(uow: LibraryUnitOfWork, id_or_slug: str) -> Collection | None:
        try:
            return await uow.taxonomy.get_collection(UUID(id_or_slug))
        except ValueError:
            return await uow.taxonomy.get_collection_by_slug(id_or_slug)
