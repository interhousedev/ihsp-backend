"""List a student's own certificates."""

from uuid import UUID

from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.ports.unit_of_work import UowFactory


class ListMyEntries:
    """Return the student's entries with their files."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, student_id: UUID) -> list[CertificateEntry]:
        """Return the entries, newest first."""
        async with self._uow_factory() as uow:
            return await uow.entries.list_for_student(student_id)
