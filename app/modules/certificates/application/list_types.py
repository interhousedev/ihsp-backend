"""List the certificate types."""

from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.ports.unit_of_work import UowFactory


class ListTypes:
    """Return all types by position."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[CertificateType]:
        """Return the types."""
        async with self._uow_factory() as uow:
            return await uow.types.list_all()
