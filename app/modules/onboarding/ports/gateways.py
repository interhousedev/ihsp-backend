"""Ports: what onboarding reads from the faces and certificates modules."""

from typing import Protocol
from uuid import UUID


class FaceGate(Protocol):
    """Whether a user has a face photo, whoever uploaded it."""

    async def has_face(self, user_id: UUID) -> bool:
        """Return True when a face profile exists."""
        ...


class EmisCertificateImport(Protocol):
    """Brings the student's EMIS certificates up to date."""

    async def refresh(self, student_id: UUID) -> None:
        """Run the import; EMIS failures propagate as their own errors."""
        ...
