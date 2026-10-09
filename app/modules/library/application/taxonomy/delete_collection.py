"""Delete a collection (the items stay in the library) (LIB-4, LIB-2)."""

from uuid import UUID

from app.modules.library.domain.errors import CollectionNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.notifications import AuditDraft


class DeleteCollection:
    """`DELETE /v1/manage/library/collections/{id}`."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, collection_id: UUID) -> None:
        """Delete the collection and its item rows; the items are not touched."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            collection = await uow.taxonomy.get_collection(collection_id)
            if collection is None:
                raise CollectionNotFoundError(
                    params={"collection_id": str(collection_id)}
                )
            await uow.taxonomy.delete_collection(collection.id)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.COLLECTION_DELETE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "collection_id": str(collection.id),
                        "slug": collection.slug,
                    },
                )
            )
            await uow.commit()
