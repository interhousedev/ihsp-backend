"""`LibrarySourceReader`: books and materials as notebook sources (LIB-10).

The notebooks module reads text and the student's own annotations through this
class. Every call opens the item again and applies `domain.bridge_rules`, so a held,
unpublished or taken-down item stops being readable at once, and a lyceum-only book
is never readable for someone who is not signed in.
"""

from typing import Final, Literal
from uuid import UUID

from app.modules.library.domain.bridge_rules import slice_pages, source_denial
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import AnnotationKind, ItemKind, TextStatus
from app.modules.library.domain.reader_annotation import Annotation
from app.modules.library.domain.reader_locator import locator_page
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.base_error import GoneError, NotFoundError
from app.shared.contracts.files import FilesApi, FullText
from app.shared.contracts.library import (
    LibraryAnnotationRef,
    LibraryFileRef,
    LibraryItemRef,
    LibrarySourceUnavailableError,
    LibraryText,
    UnavailableReason,
)

NO_TEXT_CODE: Final = (
    "files/no-text"  # the files module's error for a file without text
)
AnnotationKindName = Literal["highlight", "note", "bookmark"]
KINDS: Final[dict[AnnotationKind, AnnotationKindName]] = {
    AnnotationKind.HIGHLIGHT: "highlight",
    AnnotationKind.NOTE: "note",
    AnnotationKind.BOOKMARK: "bookmark",
}


def unavailable(
    reason: UnavailableReason, item_id: UUID
) -> LibrarySourceUnavailableError:
    """The error of the contract for a reason and an item."""
    return LibrarySourceUnavailableError(reason, item_id=item_id)


def file_ref(item_file: ItemFile) -> LibraryFileRef:
    """A file of an item as notebooks see it."""
    return LibraryFileRef(
        file_id=item_file.file_id,
        format=item_file.format.value,
        pages=item_file.pages,
        text_status=item_file.text_status.value,
        is_primary=item_file.is_primary,
    )


def item_ref(item: Item) -> LibraryItemRef:
    """The item as notebooks see it (materials are labelled with their uploader)."""
    uploader = item.material.uploader_name if item.material else ""
    return LibraryItemRef(
        id=item.id,
        kind="book" if item.kind is ItemKind.BOOK else "material",
        title=item.title,
        author_label=item.author_label or uploader,
        page_count=item.page_count,
        files=tuple(file_ref(f) for f in item.files),
    )


def annotation_ref(row: Annotation) -> LibraryAnnotationRef:
    """One stored annotation as the contract hands it over."""
    return LibraryAnnotationRef(
        kind=KINDS[row.kind],
        quote=row.quote,
        note=row.note,
        page=locator_page(row.locator),
        color=row.color.value,
        updated_at=row.updated_at,
    )


class LibrarySourceReaderImpl:
    """Implements `LibrarySourceReader` over the library unit of work and files."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files

    async def describe(self, item_id: UUID, actor: Actor) -> LibraryItemRef:
        """The item and its files; raises `LibrarySourceUnavailableError`."""
        async with self.uow_factory() as uow:
            item = await self._open(uow, item_id, actor)
        return item_ref(item)

    async def read_text(
        self,
        item_id: UUID,
        file_id: UUID,
        *,
        actor: Actor,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> LibraryText:
        """The text of a page range of one file (the whole file by default).

        Raises:
            LibrarySourceUnavailableError: The item is not usable (`not_found`,
                `unavailable`, `not_supported`) or the pages have no text (`no_text`).
        """
        async with self.uow_factory() as uow:
            item = await self._open(uow, item_id, actor)
        item_file = item.file(file_id)
        if item_file is None:
            raise unavailable("not_found", item_id)
        if item_file.text_status is not TextStatus.READY:
            raise unavailable("no_text", item_id)
        full = await self._full_text(item_id, file_id)
        cut = slice_pages(full.text, full.page_starts, page_from, page_to)
        if cut is None or not cut.text.strip():
            raise unavailable("no_text", item_id)
        return LibraryText(
            item_id=item_id,
            file_id=file_id,
            title=item.title,
            page_from=cut.page_from,
            page_to=cut.page_to,
            text=cut.text,
            page_starts=cut.page_starts,
        )

    async def read_annotations(
        self, item_id: UUID, *, actor: Actor
    ) -> list[LibraryAnnotationRef]:
        """The actor's own annotations on the item, oldest first."""
        async with self.uow_factory() as uow:
            await self._open(uow, item_id, actor)
            rows = await uow.annotations.list_for_item(actor.user_id, item_id)
        refs = [annotation_ref(row) for row in rows]
        return sorted(refs, key=lambda ref: ref.updated_at)

    # - - - Steps - - -

    @staticmethod
    async def _open(uow: LibraryUnitOfWork, item_id: UUID, actor: Actor) -> Item:
        """The item when the actor may use it as a source, else the reason why not."""
        item = await uow.items.get(item_id)
        reason = source_denial(item, actor)
        if item is None or reason is not None:
            raise unavailable(reason or "not_found", item_id)
        return item

    async def _full_text(self, item_id: UUID, file_id: UUID) -> FullText:
        """The extracted text of a file with its page offsets."""
        try:
            return await self.files.read_text_with_pages(file_id)
        except GoneError as exc:
            raise unavailable("not_found", item_id) from exc
        except NotFoundError as exc:
            reason: UnavailableReason = (
                "no_text" if exc.code == NO_TEXT_CODE else "not_found"
            )
            raise unavailable(reason, item_id) from exc
