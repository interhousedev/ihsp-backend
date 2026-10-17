"""GET /v1/certificates/me."""

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.certificates.schemas import CertificateEntryResponse


async def list_my_entries(
    container: ContainerDep, actor: StudentActor
) -> list[CertificateEntryResponse]:
    """Return the caller's certificates."""
    entries = await container.certificates.list_my_entries.execute(actor.user_id)
    return [CertificateEntryResponse.from_domain(e) for e in entries]
