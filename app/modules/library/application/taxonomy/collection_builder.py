"""Shared steps of the collection use cases: visible items, covers, read models."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.cards import pick_name
from app.modules.library.application.taxonomy.views import (
    CollectionView,
    ManageCollectionView,
)
from app.modules.library.domain.access import can_view
from app.modules.library.domain.entities import Item
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.domain.taxonomy_collections import (
    Collection,
    check_item_count,
)
from app.modules.library.domain.taxonomy_errors import CoverInvalidError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilePurpose, FilesApi

import structlog

log = structlog.get_logger(__name__)


class CollectionBuilder:
    """Checks the input of a collection and builds its read models."""

    def __init__(
        self, *, files: FilesApi, cover_ttl_seconds: int, anonymous_cards: bool
    ) -> None:
        """Store the files API and whether visitors may see UniLibrary cards."""
        self.files = files
        self.cover_ttl_seconds = cover_ttl_seconds
        self.anonymous_cards = anonymous_cards

    # - - - Items - - -

    async def visible_items(
        self, uow: LibraryUnitOfWork, item_ids: Sequence[UUID], viewer: Actor | None
    ) -> list[Item]:
        """The items the viewer may see, in the order of `item_ids`."""
        found = await uow.items.get_many(item_ids)
        return [
            found[item_id]
            for item_id in item_ids
            if item_id in found
            and can_view(found[item_id], viewer, anonymous_cards=self.anonymous_cards)
        ]

    async def checked_item_ids(
        self, uow: LibraryUnitOfWork, item_ids: Sequence[UUID], actor: Actor
    ) -> list[UUID]:
        """The ids without repeats, after checking the size and that all exist."""
        unique = list(dict.fromkeys(item_ids))
        check_item_count(len(unique))
        visible = {i.id for i in await self.visible_items(uow, unique, actor)}
        for item_id in unique:
            if item_id not in visible:
                raise ItemNotFoundError(params={"item_id": str(item_id)})
        return unique

    # - - - Cover - - -

    async def check_cover(self, file_id: UUID | None) -> None:
        """The cover, when given, is a stored file uploaded as a library cover."""
        if file_id is None:
            return
        stored = await self.files.get(file_id)
        if stored is None or stored.purpose is not FilePurpose.LIBRARY_COVER:
            raise CoverInvalidError(params={"file_id": str(file_id)})

    async def cover_url(self, file_id: UUID | None) -> str | None:
        """A short-lived URL of the cover, or None when there is none."""
        if file_id is None:
            return None
        try:
            return await self.files.download_url(
                file_id, inline=True, ttl_seconds=self.cover_ttl_seconds
            )
        except BaseError:
            log.warning("library_cover_unavailable", file_id=str(file_id))
            return None

    # - - - Read models - - -

    async def public_view(
        self, collection: Collection, item_count: int, locale: str
    ) -> CollectionView:
        """The collection as readers see it, in their language."""
        return CollectionView(
            id=collection.id,
            slug=collection.slug,
            title=pick_name(collection.title, locale),
            description=pick_name(collection.description, locale) or None,
            cover_url=await self.cover_url(collection.cover_file_id),
            item_count=item_count,
        )

    async def manage_view(
        self, collection: Collection, item_ids: Sequence[UUID]
    ) -> ManageCollectionView:
        """The collection with every language and the stored item ids."""
        return ManageCollectionView(
            id=collection.id,
            slug=collection.slug,
            title=dict(collection.title),
            description=dict(collection.description) or None,
            cover_url=await self.cover_url(collection.cover_file_id),
            published=collection.published,
            position=collection.position,
            item_ids=tuple(item_ids),
        )
