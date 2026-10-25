"""POST /v1/certificates/me."""

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.certificates.schemas import (
    CertificateEntryResponse,
    CreateEntryBody,
)


async def create_entry(
    body: CreateEntryBody, container: ContainerDep, actor: StudentActor
) -> CertificateEntryResponse:
    """Record a certificate."""
    values = body.model_dump(exclude={"type_id"}, exclude_unset=True)
    entry = await container.certificates.create_entry.execute(
        actor.user_id, body.type_id, values
    )
    return CertificateEntryResponse.from_domain(entry)
