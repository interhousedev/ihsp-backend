"""Read-only views of the students' platform certificates (admission, rating)."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from app.modules.certificates.application.list_my_entries import ListMyEntries
from app.modules.certificates.application.list_types import ListTypes
from app.modules.certificates.domain.entry import CertificateEntry
from app.shared.contracts.certificates import StudentCertificate


class AdmissionCertificatesAdapter:
    """Implements `CertificateDirectory` and `CertificateRoster` over the use cases."""

    def __init__(self, list_types: ListTypes, list_entries: ListMyEntries) -> None:
        """Keep the use cases."""
        self._types = list_types
        self._entries = list_entries

    async def for_student(self, student_id: UUID) -> list[StudentCertificate]:
        """Return the student's entries joined with their types."""
        entries = await self._entries.execute(student_id)
        return [cert for _, cert in await self._joined(entries)]

    async def for_students(
        self, student_ids: Sequence[UUID]
    ) -> dict[UUID, list[StudentCertificate]]:
        """Return each student's entries joined with their types."""
        out: dict[UUID, list[StudentCertificate]] = {}
        if not student_ids:
            return out
        entries = await self._entries.for_students(student_ids)
        for student_id, cert in await self._joined(entries):
            out.setdefault(student_id, []).append(cert)
        return out

    async def _joined(
        self, entries: Iterable[CertificateEntry]
    ) -> list[tuple[UUID, StudentCertificate]]:
        types = {t.id: t for t in await self._types.execute()}
        out: list[tuple[UUID, StudentCertificate]] = []
        for entry in entries:
            kind = types.get(entry.type_id)
            if kind is None:
                continue
            out.append(
                (
                    entry.student_id,
                    StudentCertificate(
                        entry_id=entry.id,
                        type_code=kind.code,
                        names=dict(kind.name),
                        standard=kind.standard,
                        category=kind.category,
                        issued_at=entry.issued_at,
                        expires_at=entry.expires_at,
                        values=dict(entry.custom_values),
                    ),
                )
            )
        return out
