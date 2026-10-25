"""Open a certificate file: the owner, Administration or the group's curator."""

from uuid import UUID

from app.modules.certificates.domain.errors import (
    CertificateFileNotFoundError,
    NotCuratorError,
)
from app.modules.certificates.ports.student_directory import StudentDirectory
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilesApi


class GetFileDownload:
    """Return a presigned URL for an attached file when the caller may read it."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        directory: StudentDirectory,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._files = files
        self._directory = directory

    async def execute(self, actor: Actor, file_id: UUID) -> str:
        """Return the URL; a file of someone else's group is forbidden."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.entry_of_file(file_id)
        if entry is None:
            raise CertificateFileNotFoundError()
        if entry.student_id != actor.user_id and not actor.has(Role.ADMIN):
            await self._check_curator(actor, entry.student_id)
        return await self._files.download_url(file_id)

    async def _check_curator(self, actor: Actor, student_id: UUID) -> None:
        student = await self._directory.student(student_id)
        curated = await self._directory.curated_group_ids(actor.user_id)
        if student is None or student.group_id not in curated:
            raise NotCuratorError()
