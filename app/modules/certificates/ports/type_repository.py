"""Port: storage of certificate types."""

from typing import Protocol
from uuid import UUID

from app.modules.certificates.domain.certificate_type import CertificateType


class CertificateTypeRepository(Protocol):
    """Certificate types."""

    async def list_all(self) -> list[CertificateType]:
        """Return all types by position."""
        ...

    async def get(self, type_id: UUID) -> CertificateType | None:
        """Return the type or None."""
        ...

    async def get_by_code(self, code: str) -> CertificateType | None:
        """Return the type with this code or None."""
        ...

    async def add(self, kind: CertificateType) -> None:
        """Insert a type."""
        ...

    async def save(self, kind: CertificateType) -> None:
        """Write the type's fields."""
        ...

    async def delete(self, type_id: UUID) -> None:
        """Delete the type."""
        ...

    async def next_position(self) -> int:
        """Return the position after the last type."""
        ...
