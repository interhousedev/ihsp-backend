"""Admission's read-only view of the student's platform certificates."""

from uuid import UUID

from app.modules.certificates.application.list_my_entries import ListMyEntries
from app.modules.certificates.application.list_types import ListTypes
from app.shared.contracts.certificates import StudentCertificate


class AdmissionCertificatesAdapter:
    """Implements `CertificateDirectory` over the certificates use cases."""

    def __init__(self, list_types: ListTypes, list_entries: ListMyEntries) -> None:
        """Keep the use cases."""
        self._types = list_types
        self._entries = list_entries

    async def for_student(self, student_id: UUID) -> list[StudentCertificate]:
        """Return the student's entries joined with their types."""
        types = {t.id: t for t in await self._types.execute()}
        out: list[StudentCertificate] = []
        for entry in await self._entries.execute(student_id):
            kind = types.get(entry.type_id)
            if kind is None:
                continue
            out.append(
                StudentCertificate(
                    entry_id=entry.id,
                    type_code=kind.code,
                    names=dict(kind.name),
                    standard=kind.standard,
                    category=kind.category,
                    issued_at=entry.issued_at,
                    expires_at=entry.expires_at,
                    values=dict(entry.custom_values),
                )
            )
        return out
