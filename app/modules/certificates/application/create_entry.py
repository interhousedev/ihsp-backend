"""Add a certificate to a student's list."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.domain.entry_rules import apply_values
from app.modules.certificates.domain.errors import CertificateTypeNotFoundError
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateEntry:
    """Record a certificate by hand."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, student_id: UUID, type_id: UUID, values: Mapping[str, Any]
    ) -> CertificateEntry:
        """Create the entry; the values must fit the type."""
        async with self._uow_factory() as uow:
            kind = await uow.types.get(type_id)
            if kind is None:
                raise CertificateTypeNotFoundError()
            entry = CertificateEntry(
                id=new_id(),
                student_id=student_id,
                type_id=type_id,
                created_at=self._clock.now(),
            )
            apply_values(kind, entry, values)
            await uow.entries.add(entry)
            await uow.commit()
        return entry
