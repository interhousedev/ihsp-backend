"""Delete one of the student's certificates with its files."""

from uuid import UUID

from app.modules.certificates.domain.errors import CertificateEntryNotFoundError
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilesApi


class DeleteEntry:
    """Remove the entry and free its files (and the student's quota)."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def execute(self, student_id: UUID, entry_id: UUID) -> None:
        """Delete the entry, then its stored files."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if entry is None or entry.student_id != student_id:
                raise CertificateEntryNotFoundError()
            await uow.entries.delete(entry_id)
            await uow.commit()
        for file in entry.files:
            await self._files.delete_file(file.id)
