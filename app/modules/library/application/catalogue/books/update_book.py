"""Edit a book (PATCH /manage/library/books/{id})."""

from collections.abc import Mapping
from uuid import UUID

from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.detail import ItemDetailView
from app.modules.library.domain.catalogue_books import (
    BookData,
    apply_book_data,
    book_data_from,
    check_book_data,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind, ItemStatus
from app.modules.library.domain.errors import NotEditableError, RightsIncompleteError
from app.modules.library.domain.rights import publish_missing
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor

RIGHTS_FIELDS = frozenset(
    {"rights", "licence", "rights_basis", "rights_proof_file_id", "visibility"}
)


class UpdateBook:
    """Change the fields that were sent; the search text is rebuilt every time."""

    def __init__(self, *, uow_factory: UowFactory, support: BookSupport) -> None:
        """Store the unit of work factory and the shared book helpers."""
        self.uow_factory = uow_factory
        self.support = support

    async def execute(
        self,
        actor: Actor,
        book_id: UUID,
        changes: Mapping[str, object],
        *,
        accept_language: str | None = None,
    ) -> ItemDetailView:
        """Apply `changes` (field name to domain value) to the stored book."""
        require_librarian(actor)
        now = self.support.clock.now()
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id, lock=True)
            if item.status is ItemStatus.GONE:
                raise NotEditableError(support_details="the book is gone")
            subjects = (await uow.items.subject_links([item.id])).get(item.id, [])
            topics = (await uow.items.topic_links([item.id])).get(item.id, [])
            current = book_data_from(item, subjects, topics)
            data = BookData.model_validate({**current.model_dump(), **changes})
            check_book_data(data)
            await self.support.validate_refs(uow, actor, data, previous=current)
            apply_book_data(item, data, now=now)
            await self._keep_published_complete(uow, item)
            await uow.items.save(item)
            await uow.items.set_subject_links(item.id, data.subjects)
            await uow.items.set_topic_links(item.id, data.topics)
            await self._log(uow, actor, item.id, changes)
            await uow.commit()
            return await self.support.detail_view(uow, item, actor, accept_language)

    async def _keep_published_complete(
        self, uow: LibraryUnitOfWork, item: Item
    ) -> None:
        if item.status is not ItemStatus.PUBLISHED:
            return
        missing = publish_missing(
            await self.support.facts(uow, item), today=self.support.today()
        )
        if missing:
            raise RightsIncompleteError(
                params={"missing": missing}, support_details="published book incomplete"
            )

    async def _log(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        item_id: UUID,
        changes: Mapping[str, object],
    ) -> None:
        now = self.support.clock.now()
        await uow.events.append(
            item_id,
            EventKind.EDITED,
            at=now,
            actor_id=actor.user_id,
            data={"fields": sorted(changes)},
        )
        if RIGHTS_FIELDS & set(changes):
            await uow.events.append(
                item_id,
                EventKind.RIGHTS_CHANGED,
                at=now,
                actor_id=actor.user_id,
                data={"fields": sorted(RIGHTS_FIELDS & set(changes))},
            )
