"""Port: indexed text pages (catalogue area)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.shared.contracts.files import TextBox


@dataclass(frozen=True, slots=True)
class IndexedPage:
    """One page of extracted text.

    `text_norm` is the search form (Latin-normalised for Uzbek items); `text` is what
    the reader and the text endpoint show.
    """

    page: int
    text: str
    text_norm: str
    source: str = "text_layer"
    boxes: tuple[TextBox, ...] = ()


class PageRepository(Protocol):
    """Pages of a file, for full-text hits with a page and `GET /items/{id}/text`."""

    async def replace(
        self, item_id: UUID, file_id: UUID, pages: Sequence[IndexedPage]
    ) -> None:
        """Replace all pages of the file (the scan job may run again)."""
        ...

    async def pages(
        self, item_id: UUID, file_id: UUID, page_from: int, page_to: int
    ) -> list[IndexedPage]:
        """Pages `page_from` to `page_to` inclusive, in order (missing ones skipped)."""
        ...

    async def count(self, item_id: UUID, file_id: UUID) -> int:
        """How many pages of the file are indexed."""
        ...

    async def delete(self, item_id: UUID, file_id: UUID) -> None:
        """Forget the pages of the file."""
        ...

    async def search(
        self, item_id: UUID, file_id: UUID, needle: str, limit: int
    ) -> list[IndexedPage]:
        """Pages whose folded text contains `needle`, in order, at most `limit`."""
        ...

    async def stale_files(
        self, after: UUID | None, limit: int
    ) -> list[tuple[UUID, UUID]]:
        """`(item_id, file_id)` of files with pages not yet folded, by file id."""
        ...
