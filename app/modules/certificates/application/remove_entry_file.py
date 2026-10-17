"""Detach and delete a file of one of the student's certificates."""

from uuid import UUID

from app.modules.certificates.domain.errors import (
    CertificateEntryNotFoundError,
    CertificateFileNotFoundError,
)
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilesApi


class RemoveEntryFile:
    """Remove the file row, then the stored object."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def execute(self, student_id: UUID, entry_id: UUID, file_id: UUID) -> None:
        """Delete the file of the student's entry."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if entry is None or entry.student_id != student_id:
                raise CertificateEntryNotFoundError()
            if all(file.id != file_id for file in entry.files):
                raise CertificateFileNotFoundError()
            await uow.entries.remove_file(file_id)
            await uow.commit()
        await self._files.delete_file(file_id)
