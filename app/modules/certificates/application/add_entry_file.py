"""Attach a file to one of the student's certificates."""

from uuid import UUID

from app.modules.certificates.domain.entry import EntryFile
from app.modules.certificates.domain.errors import CertificateEntryNotFoundError
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope


class AddEntryFile:
    """Store the bytes in the student's files (their quota counts) and attach."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files

    async def execute(
        self, student_id: UUID, entry_id: UUID, *, name: str, data: bytes
    ) -> EntryFile:
        """Attach the file; the files module checks type, size and quota."""
        await self._check_entry(student_id, entry_id)
        stored = await self._files.store_bytes(
            owner_id=student_id,
            scope=FileScope.STUDENT,
            purpose=FilePurpose.CERTIFICATE,
            name=name,
            data=data,
        )
        file = EntryFile(
            id=stored.id,
            entry_id=entry_id,
            name=stored.name,
            size=stored.byte_size,
            content_type=stored.content_type,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.entries.add_file(file)
                await uow.commit()
        except Exception:
            await self._files.delete_file(stored.id)
            raise
        return file

    async def _check_entry(self, student_id: UUID, entry_id: UUID) -> None:
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
        if entry is None or entry.student_id != student_id:
            raise CertificateEntryNotFoundError()
