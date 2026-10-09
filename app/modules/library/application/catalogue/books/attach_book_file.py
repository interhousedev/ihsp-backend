"""Attach an uploaded file to a book and start the scan job."""

from uuid import UUID

from app.modules.library.application.catalogue.books.support import BookSupport
from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.detail import ItemFileView, file_view
from app.modules.library.domain.catalogue_errors import InvalidFileError
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import EventKind, FileFormat, TextStatus
from app.modules.library.domain.errors import FileTooLargeError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.contracts.files import FileRef, FilesApi, FileScope
from app.shared.tasks import TaskKicker

PROCESS_TASK = "library.process_item_file"
BOOK_FORMATS = frozenset(
    {FileFormat.PDF, FileFormat.EPUB, FileFormat.MD, FileFormat.TXT}
)
_CONTENT_TYPE_HINT = {
    FileFormat.PDF: "pdf",
    FileFormat.EPUB: "epub",
}
BYTES_PER_MB = 1_048_576


class AttachBookFile:
    """Check the upload, record it as an `ItemFile` and queue text extraction."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        support: BookSupport,
        files: FilesApi,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.support = support
        self.files = files
        self.kicker = kicker

    async def execute(
        self,
        actor: Actor,
        book_id: UUID,
        *,
        file_id: UUID,
        file_format: FileFormat,
        is_primary: bool,
    ) -> ItemFileView:
        """Attach the file; the first file of a book is always the primary one."""
        require_librarian(actor)
        ref = await self._checked_upload(actor, file_id, file_format)
        async with self.uow_factory() as uow:
            item = await self.support.get_book(uow, book_id, lock=True)
            existing = item.file(file_id)
            if existing is not None:
                return file_view(existing)
            stored = await self._add(uow, item, ref, file_format, is_primary)
            await uow.events.append(
                item.id,
                EventKind.EDITED,
                at=self.support.clock.now(),
                actor_id=actor.user_id,
                data={"file_id": str(file_id), "format": file_format.value},
            )
            uow.after_commit(lambda: self._queue_scan(item.id, file_id))
            await uow.commit()
        return file_view(stored)

    async def _checked_upload(
        self, actor: Actor, file_id: UUID, file_format: FileFormat
    ) -> FileRef:
        if file_format not in BOOK_FORMATS:
            raise InvalidFileError(
                params={"format": file_format.value}, support_details="format"
            )
        ref = await self.files.get(file_id)
        if (
            ref is None
            or ref.scope is not FileScope.LIBRARY
            or ref.owner_id != actor.user_id
            or ref.status != "ready"
        ):
            raise InvalidFileError(support_details=f"file {file_id} is not usable")
        hint = _CONTENT_TYPE_HINT.get(file_format)
        if hint and hint not in ref.content_type:
            raise InvalidFileError(support_details=f"{ref.content_type} is not {hint}")
        limit = self.support.settings.file_max_bytes
        if ref.byte_size > limit:
            raise FileTooLargeError(params={"max_mb": limit // BYTES_PER_MB})
        return ref

    async def _add(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        ref: FileRef,
        file_format: FileFormat,
        is_primary: bool,
    ) -> ItemFile:
        primary = is_primary or not item.files
        if primary:
            for other in item.files:
                if other.is_primary:
                    other.is_primary = False
                    await uow.items.save_file(other)
        stored = ItemFile(
            item_id=item.id,
            file_id=ref.id,
            format=file_format,
            byte_size=ref.byte_size,
            is_primary=primary,
            text_status=TextStatus.PENDING,
        )
        await uow.items.add_file(stored)
        item.updated_at = self.support.clock.now()
        await uow.items.save(item)
        return stored

    async def _queue_scan(self, item_id: UUID, file_id: UUID) -> None:
        await self.kicker.kick(PROCESS_TASK, item_id=str(item_id), file_id=str(file_id))
