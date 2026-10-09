"""Create a draft book (POST /manage/library/books)."""

from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.detail import ItemDetailView
from app.modules.library.domain.catalogue_books import (
    BookData,
    check_book_data,
    new_book,
)
from app.modules.library.domain.enums import EventKind
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id


class CreateBook:
    """A librarian starts a book; it stays a draft until the checklist passes."""

    def __init__(self, *, uow_factory: UowFactory, support: BookSupport) -> None:
        """Store the unit of work factory and the shared book helpers."""
        self.uow_factory = uow_factory
        self.support = support

    async def execute(
        self, actor: Actor, data: BookData, *, accept_language: str | None = None
    ) -> ItemDetailView:
        """Validate the form, store the draft with its tags and log the event."""
        require_librarian(actor)
        check_book_data(data)
        now = self.support.clock.now()
        async with self.uow_factory() as uow:
            await self.support.validate_refs(uow, actor, data)
            item = new_book(data, item_id=new_id(), owner_id=actor.user_id, now=now)
            await uow.items.add(item)
            await uow.items.set_subject_links(item.id, data.subjects)
            await uow.items.set_topic_links(item.id, data.topics)
            await uow.events.append(
                item.id, EventKind.CREATED, at=now, actor_id=actor.user_id
            )
            await uow.commit()
            return await self.support.detail_view(uow, item, actor, accept_language)
