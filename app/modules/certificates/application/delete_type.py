"""Delete a certificate type (administrator)."""

from uuid import UUID

from app.modules.certificates.domain.errors import (
    CertificateTypeBuiltinError,
    CertificateTypeInUseError,
    CertificateTypeNotFoundError,
)
from app.modules.certificates.ports.unit_of_work import UowFactory


class DeleteType:
    """Delete a custom type nobody uses."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, type_id: UUID) -> None:
        """Delete the type unless it is built in or entries use it."""
        async with self._uow_factory() as uow:
            kind = await uow.types.get(type_id)
            if kind is None:
                raise CertificateTypeNotFoundError()
            if kind.builtin:
                raise CertificateTypeBuiltinError()
            if await uow.entries.count_for_type(type_id) > 0:
                raise CertificateTypeInUseError()
            await uow.types.delete(type_id)
            await uow.commit()
