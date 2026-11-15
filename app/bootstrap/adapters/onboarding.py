"""Adapters of the onboarding module: faces and certificates use cases."""

from uuid import UUID

from app.modules.certificates.application.import_emis import ImportEmis
from app.modules.faces.application.face_queries import HasFace


class OnboardingFacesAdapter:
    """Whether a face photo exists, through the faces use case."""

    def __init__(self, has_face: HasFace) -> None:
        """Store the use case."""
        self._has_face = has_face

    async def has_face(self, user_id: UUID) -> bool:
        """Return True when the user has a face profile."""
        return await self._has_face.execute(user_id)


class OnboardingCertificatesAdapter:
    """EMIS certificate import, through the certificates use case."""

    def __init__(self, import_emis: ImportEmis) -> None:
        """Store the use case."""
        self._import_emis = import_emis

    async def refresh(self, student_id: UUID) -> None:
        """Run the import for the student."""
        await self._import_emis.execute(student_id)
