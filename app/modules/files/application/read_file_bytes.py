"""Read a whole file from storage (Telegram documents, mail forwarding)."""

from uuid import UUID

from app.modules.files.domain.errors import (
    FileDeletedError,
    FileNotReadyError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory

_READABLE = frozenset({FileStatus.PROCESSING, FileStatus.READY})


class ReadFileBytes:
    """Return the content of a file that passed the upload checks."""

    def __init__(self, *, uow_factory: UowFactory, storage: ObjectStorage) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage

    async def execute(self, file_id: UUID) -> bytes:
        """Return the bytes; the caller has already checked access."""
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        if file.status == FileStatus.DELETED:
            raise FileDeletedError()
        if file.status not in _READABLE:
            raise FileNotReadyError(params={"status": file.status.value})
        return await self._storage.get(file.key)
