"""Change the sequence of reading lists (librarians only)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.reading_list import reordered
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class ReorderReadingLists:
    """`PUT /v1/library/reading-lists/order`: the manual order everyone sees."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, ids: Sequence[UUID]) -> None:
        """Put the given lists in the given sequence, inside the slots they hold.

        Lists left out keep their places, so a filtered view can be reordered.
        """
        if not is_librarian(actor):
            raise ListForbiddenError(params={})
        async with self.uow_factory() as uow:
            await uow.lists.store_order(reordered(await uow.lists.order(), ids))
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_REORDER.value,
                    actor_id=actor.user_id,
                    metadata={"count": len(ids)},
                )
            )
            await uow.commit()
