"""Change a collection: texts, cover, publication, items (LIB-4, LIB-2)."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.views import ManageCollectionView
from app.modules.library.domain.errors import CollectionNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_collections import (
    clean_description,
    clean_title,
)
from app.modules.library.domain.taxonomy_unset import UNSET, Unset
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft


class UpdateCollection:
    """`PATCH /v1/manage/library/collections/{id}`: only the fields that were sent."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, builder: CollectionBuilder
    ) -> None:
        """Store the unit of work factory, the clock and the collection helpers."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.builder = builder

    async def execute(
        self,
        actor: Actor,
        collection_id: UUID,
        *,
        title: Mapping[str, str] | Unset = UNSET,
        description: Mapping[str, str] | None | Unset = UNSET,
        cover_file_id: UUID | None | Unset = UNSET,
        published: bool | Unset = UNSET,
        item_ids: Sequence[UUID] | Unset = UNSET,
    ) -> ManageCollectionView:
        """Apply the given changes; `None` clears the description or the cover.

        The slug stays, so shared links keep working. `item_ids` replaces the items.
        """
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            collection = await uow.taxonomy.get_collection(collection_id)
            if collection is None:
                raise CollectionNotFoundError(
                    params={"collection_id": str(collection_id)}
                )
            if not isinstance(title, Unset):
                collection.title = clean_title(title)
            if not isinstance(description, Unset):
                collection.description = clean_description(description)
            if not isinstance(cover_file_id, Unset):
                await self.builder.check_cover(cover_file_id)
                collection.cover_file_id = cover_file_id
            if not isinstance(published, Unset):
                collection.published = published
            if not isinstance(item_ids, Unset):
                ids = await self.builder.checked_item_ids(uow, item_ids, actor)
                await uow.taxonomy.set_collection_items(collection.id, ids)
            collection.updated_at = self.clock.now()
            await uow.taxonomy.save_collection(collection)
            stored = (await uow.taxonomy.collection_item_ids([collection.id])).get(
                collection.id, []
            )
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.COLLECTION_UPDATE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "collection_id": str(collection.id),
                        "item_count": len(stored),
                        "published": collection.published,
                    },
                )
            )
            await uow.commit()
        return await self.builder.manage_view(collection, stored)
