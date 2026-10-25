"""Delete a reading list and its entries (LIB-4)."""

from uuid import UUID

from app.modules.library.domain.errors import ListNotFoundError
from app.modules.library.domain.reading_list_policy import (
    can_edit_list,
    can_view_list,
)
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class DeleteReadingList:
    """`DELETE /v1/library/reading-lists/{id}`: the owner and librarians."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, list_id: UUID) -> None:
        """Remove the list; a list the caller cannot see is not found."""
        async with self.uow_factory() as uow:
            lst = await uow.lists.get(list_id, lock=True)
            if lst is None or not can_view_list(lst, actor, group_id=None):
                raise ListNotFoundError(params={"list_id": str(list_id)})
            if not can_edit_list(lst, actor):
                raise ListForbiddenError(params={"list_id": str(list_id)})
            await uow.lists.delete(list_id)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_DELETE.value,
                    actor_id=actor.user_id,
                    metadata={"list_id": str(list_id), "title": lst.title},
                )
            )
            await uow.commit()
