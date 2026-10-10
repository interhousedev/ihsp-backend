"""The editor's data of a book (GET /manage/library/books/{id})."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.detail import ItemDetailView
from app.modules.library.domain.catalogue_books import BookData, book_data_from
from app.modules.library.domain.rights import ChecklistEntry, publish_checklist
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class BookDraftView:
    """`BookDraft` of the TypeScript contract."""

    item: ItemDetailView
    data: BookData
    checklist: list[ChecklistEntry]


class GetBookDraft:
    """The input as saved, the detail and the publish checklist of a book."""

    def __init__(self, *, uow_factory: UowFactory, support: BookSupport) -> None:
        """Store the unit of work factory and the shared book helpers."""
        self.uow_factory = uow_factory
        self.support = support

    async def execute(
        self, actor: Actor, book_id: UUID, *, accept_language: str | None = None
    ) -> BookDraftView:
        """Everything the book editor needs, whatever the status of the book."""
        require_librarian(actor)
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id)
            subjects = (await uow.items.subject_links([item.id])).get(item.id, [])
            topics = (await uow.items.topic_links([item.id])).get(item.id, [])
            tags = (await uow.labels.item_tags([item.id])).get(item.id, [])
            facts = await self.support.facts(uow, item)
            detail = await self.support.detail_view(uow, item, actor, accept_language)
        return BookDraftView(
            item=detail,
            data=book_data_from(item, subjects, topics, tags),
            checklist=publish_checklist(facts, today=self.support.today()),
        )
