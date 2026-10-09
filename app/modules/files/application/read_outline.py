"""Read the table of contents found while processing a file."""

from uuid import UUID

from app.modules.files.domain.errors import FileDeletedError, StoredFileNotFoundError
from app.modules.files.domain.outline import OUTLINE_KEY, outline_from_metadata
from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.contracts.files import OutlineEntry


class ReadOutline:
    """The outline of a PDF (bookmarks) or EPUB (contents), for the reader."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, file_id: UUID) -> list[OutlineEntry]:
        """Return the entries; [] for files without one or processed before.

        Raises:
            StoredFileNotFoundError: The file does not exist.
            FileDeletedError: The file was deleted.
        """
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        if file.status == FileStatus.DELETED:
            raise FileDeletedError()
        return outline_from_metadata(file.metadata.get(OUTLINE_KEY))
