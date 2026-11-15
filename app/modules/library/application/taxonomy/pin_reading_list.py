"""Pin or unpin a reading list (librarians only)."""

from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListDetailView
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.errors import ListNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class PinReadingList:
    """`PUT /v1/library/reading-lists/{id}/pin`: pinned lists are shown first."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        builder: ReadingListBuilder,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.builder = builder

    async def execute(
        self,
        actor: Actor,
        list_id: UUID,
        *,
        pinned: bool,
        accept_language: str | None = None,
    ) -> ReadingListDetailView:
        """Set the pin; the list stays otherwise untouched."""
        if not is_librarian(actor):
            raise ListForbiddenError(params={"list_id": str(list_id)})
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            lst = await uow.lists.get(list_id, lock=True)
            if lst is None:
                raise ListNotFoundError(params={"list_id": str(list_id)})
            lst.pinned = pinned
            await uow.lists.save(lst)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_PIN.value,
                    actor_id=actor.user_id,
                    metadata={"list_id": str(lst.id), "pinned": pinned},
                )
            )
            await uow.commit()
            return await self.builder.detail_for(uow, lst, viewer=actor, locale=locale)
