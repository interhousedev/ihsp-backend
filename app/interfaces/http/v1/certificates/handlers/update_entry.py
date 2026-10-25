"""PATCH /v1/certificates/me/{entry_id}."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.certificates.schemas import (
    CertificateEntryResponse,
    UpdateEntryBody,
)


async def update_entry(
    entry_id: UUID,
    body: UpdateEntryBody,
    container: ContainerDep,
    actor: StudentActor,
) -> CertificateEntryResponse:
    """Change the sent fields of the caller's certificate."""
    entry = await container.certificates.update_entry.execute(
        actor.user_id, entry_id, body.model_dump(exclude_unset=True)
    )
    return CertificateEntryResponse.from_domain(entry)
