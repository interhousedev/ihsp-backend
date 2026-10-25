"""Edit a certificate type (administrator)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.errors import (
    CertificateTypeCodeTakenError,
    CertificateTypeNotFoundError,
)
from app.modules.certificates.domain.type_rules import apply_changes
from app.modules.certificates.ports.unit_of_work import UowFactory


class UpdateType:
    """Change fields of a type; a built-in type keeps its code."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(
        self, type_id: UUID, changes: Mapping[str, Any]
    ) -> CertificateType:
        """Apply the changes and return the type."""
        async with self._uow_factory() as uow:
            kind = await uow.types.get(type_id)
            if kind is None:
                raise CertificateTypeNotFoundError()
            apply_changes(kind, changes)
            other = await uow.types.get_by_code(kind.code)
            if other is not None and other.id != kind.id:
                raise CertificateTypeCodeTakenError()
            await uow.types.save(kind)
            await uow.commit()
        return kind
