"""Publish, unpublish and take down books (POST /manage/library/books/{id}/{action})."""

from uuid import UUID

from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.detail import ItemDetailView
from app.modules.library.domain.catalogue_books import (
    book_data_from,
    check_book_data,
    publish_book,
    take_down_book,
    unpublish_book,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind
from app.modules.library.domain.errors import ReasonRequiredError, RightsIncompleteError
from app.modules.library.domain.rights import publish_missing
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.library_audit import LibraryAuditType
from app.shared.notifications import AuditDraft


class _BookStatusChange:
    """Shared steps: load and lock the book, change it, log, audit, commit."""

    def __init__(self, *, uow_factory: UowFactory, support: BookSupport) -> None:
        """Store the unit of work factory and the shared book helpers."""
        self.uow_factory = uow_factory
        self.support = support

    async def _record(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        item: Item,
        *,
        event: EventKind,
        audit: LibraryAuditType,
        reason: str | None,
    ) -> None:
        now = self.support.clock.now()
        await uow.items.save(item)
        data = {"reason": reason} if reason else {}
        await uow.events.append(
            item.id, event, at=now, actor_id=actor.user_id, data=data
        )
        uow.audit(
            AuditDraft(
                type=audit.value,
                actor_id=actor.user_id,
                metadata={"item_id": str(item.id), "title": item.title, **data},
            )
        )


class PublishBook(_BookStatusChange):
    """Run the checklist; a complete draft becomes visible to its audience."""

    async def execute(
        self, actor: Actor, book_id: UUID, *, accept_language: str | None = None
    ) -> ItemDetailView:
        """Publish, or fail with `library/rights-incomplete` listing what is missing."""
        require_librarian(actor)
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id, lock=True)
            subjects = (await uow.items.subject_links([item.id])).get(item.id, [])
            topics = (await uow.items.topic_links([item.id])).get(item.id, [])
            check_book_data(book_data_from(item, subjects, topics))
            missing = publish_missing(
                await self.support.facts(uow, item), today=self.support.today()
            )
            if missing:
                raise RightsIncompleteError(
                    params={"missing": missing}, support_details="checklist failed"
                )
            publish_book(item, actor_id=actor.user_id, now=self.support.clock.now())
            await self._record(
                uow,
                actor,
                item,
                event=EventKind.APPROVED,
                audit=LibraryAuditType.BOOK_PUBLISH,
                reason=None,
            )
            await uow.commit()
            return await self.support.detail_view(uow, item, actor, accept_language)


class UnpublishBook(_BookStatusChange):
    """Withdraw a book from the catalogue; the file and the shelves stay."""

    async def execute(
        self,
        actor: Actor,
        book_id: UUID,
        *,
        reason: str | None = None,
        accept_language: str | None = None,
    ) -> ItemDetailView:
        """Unpublish with an optional note."""
        require_librarian(actor)
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id, lock=True)
            unpublish_book(
                item,
                actor_id=actor.user_id,
                now=self.support.clock.now(),
                note=reason,
            )
            await self._record(
                uow,
                actor,
                item,
                event=EventKind.UNPUBLISHED,
                audit=LibraryAuditType.UNPUBLISH,
                reason=reason,
            )
            await uow.commit()
            return await self.support.detail_view(uow, item, actor, accept_language)


class TakedownBook(_BookStatusChange):
    """Remove a book for a recorded reason (copyright, wrong content, ...)."""

    async def execute(
        self,
        actor: Actor,
        book_id: UUID,
        *,
        reason: str | None,
        accept_language: str | None = None,
    ) -> ItemDetailView:
        """Take the book down; a reason is required and kept with the item."""
        require_librarian(actor)
        note = (reason or "").strip()
        if not note:
            raise ReasonRequiredError(params={"field": "reason"})
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id, lock=True)
            take_down_book(
                item, actor_id=actor.user_id, now=self.support.clock.now(), note=note
            )
            await self._record(
                uow,
                actor,
                item,
                event=EventKind.UNPUBLISHED,
                audit=LibraryAuditType.TAKEDOWN,
                reason=note,
            )
            await uow.commit()
            return await self.support.detail_view(uow, item, actor, accept_language)
