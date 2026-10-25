"""Edit one of the student's certificates."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.domain.entry_rules import apply_values
from app.modules.certificates.domain.errors import (
    CertificateEntryNotFoundError,
    CertificateTypeNotFoundError,
)
from app.modules.certificates.ports.unit_of_work import UowFactory


class UpdateEntry:
    """Change fields of the student's own entry."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(
        self, student_id: UUID, entry_id: UUID, values: Mapping[str, Any]
    ) -> CertificateEntry:
        """Apply the values; someone else's entry is "not found"."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if entry is None or entry.student_id != student_id:
                raise CertificateEntryNotFoundError()
            kind = await uow.types.get(entry.type_id)
            if kind is None:
                raise CertificateTypeNotFoundError()
            apply_values(kind, entry, values)
            await uow.entries.save(entry)
            await uow.commit()
        return entry
