"""Read one page (up to 8 KB) of a file's extracted text (FILE-7)."""

from uuid import UUID

from app.modules.files.domain.errors import (
    FileDeletedError,
    NoTextError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.text_pages import get_page, split_pages
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.contracts.files import TextPage


class ReadTextPage:
    """Pages of the text sidecar; page numbers start at 1."""

    def __init__(self, *, uow_factory: UowFactory, storage: ObjectStorage) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage

    async def execute(self, file_id: UUID, page: int) -> TextPage:
        """Return the page; NotFound when there is no text or the page is missing."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        if file.status == FileStatus.DELETED:
            raise FileDeletedError()
        if file.text_bytes is None:
            raise NoTextError()
        text = (await self._storage.get(file.text_key)).decode()
        pages = split_pages(text)
        return TextPage(
            file_id=file_id, page=page, pages=len(pages), text=get_page(pages, page)
        )
