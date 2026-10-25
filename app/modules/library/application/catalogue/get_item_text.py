"""Extracted text of a book or material, page by page (GET .../items/{id}/text)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.catalogue.common import (
    anonymous_cards,
    load_visible,
)
from app.modules.library.domain.access import can_read_content
from app.modules.library.domain.catalogue_text import split_pages
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import ItemKind, TextStatus
from app.modules.library.domain.errors import (
    ItemNotFoundError,
    NotSupportedError,
    TextUnavailableError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.base_error import BaseError, ValidationFailedError
from app.shared.contracts.files import FilesApi

MAX_PAGES_PER_CALL = 50


@dataclass(frozen=True, slots=True)
class TextPageView:
    """One page of text."""

    page: int
    text: str


class GetItemText:
    """The text pages of the primary file, for the reader's search and notebooks."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.settings = settings

    async def execute(
        self,
        actor: Actor | None,
        item_id: UUID,
        *,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> list[TextPageView]:
        """Pages `page_from` to `page_to` (at most 50 at a time)."""
        first = page_from or 1
        last = min(
            page_to or first + MAX_PAGES_PER_CALL - 1, first + MAX_PAGES_PER_CALL - 1
        )
        if first < 1 or last < first:
            raise ValidationFailedError(params={"field": "page_from"})
        cards = anonymous_cards(self.settings)
        async with self.uow_factory() as uow:
            item = await load_visible(uow, str(item_id), actor, cards=cards)
            stored = self._readable_file(item, actor, cards)
            indexed = await uow.pages.pages(item.id, stored.file_id, first, last)
            if indexed:
                return [TextPageView(p.page, p.text) for p in indexed]
            if await uow.pages.count(item.id, stored.file_id):
                return []
        return await self._from_files(stored.file_id, first, last)

    def _readable_file(self, item: Item, actor: Actor | None, cards: bool) -> ItemFile:
        if item.kind is ItemKind.EXTERNAL:
            raise NotSupportedError(support_details="external items have no text")
        if not can_read_content(item, actor, anonymous_cards=cards):
            raise ItemNotFoundError(support_details="content is not readable")
        stored = item.primary_file
        if stored is None or stored.text_status is not TextStatus.READY:
            raise TextUnavailableError(support_details="text is not ready")
        return stored

    async def _from_files(
        self, file_id: UUID, first: int, last: int
    ) -> list[TextPageView]:
        try:
            full = await self.files.read_text_with_pages(file_id)
        except BaseError as exc:
            raise TextUnavailableError(support_details=exc.code) from exc
        pages = split_pages(full.text, full.page_starts)
        return [
            TextPageView(number, pages[number - 1])
            for number in range(first, min(last, len(pages)) + 1)
        ]
