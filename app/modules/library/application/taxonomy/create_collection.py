"""Create a curated collection (LIB-4, LIB-2)."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.library.application.cards import pick_name
from app.modules.library.application.taxonomy.collection_builder import (
    CollectionBuilder,
)
from app.modules.library.application.taxonomy.views import ManageCollectionView
from app.modules.library.domain.slugs import make_slug
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_collections import (
    Collection,
    clean_description,
    clean_title,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


class CreateCollection:
    """`POST /v1/manage/library/collections`: items are part of the body."""

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
        *,
        title: Mapping[str, str],
        description: Mapping[str, str] | None = None,
        cover_file_id: UUID | None = None,
        published: bool = False,
        item_ids: Sequence[UUID] = (),
    ) -> ManageCollectionView:
        """Store the collection last in the order, with its items as given."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        names = clean_title(title)
        await self.builder.check_cover(cover_file_id)
        async with self.uow_factory() as uow:
            ids = await self.builder.checked_item_ids(uow, item_ids, actor)
            now = self.clock.now()
            collection_id = new_id()
            collection = Collection(
                id=collection_id,
                slug=make_slug(pick_name(names, "en"), collection_id),
                title=names,
                description=clean_description(description),
                published=published,
                position=await uow.taxonomy.next_collection_position(),
                created_at=now,
                updated_at=now,
                cover_file_id=cover_file_id,
            )
            await uow.taxonomy.add_collection(collection)
            await uow.taxonomy.set_collection_items(collection.id, ids)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.COLLECTION_CREATE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "collection_id": str(collection.id),
                        "slug": collection.slug,
                        "item_count": len(ids),
                        "published": published,
                    },
                )
            )
            await uow.commit()
        return await self.builder.manage_view(collection, ids)
