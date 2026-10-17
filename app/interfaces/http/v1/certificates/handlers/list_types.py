"""GET /v1/certificates/types."""

from app.interfaces.http.v1.certificates.deps import AnyActor, ContainerDep
from app.interfaces.http.v1.certificates.schemas import CertificateTypeResponse


async def list_types(
    container: ContainerDep, actor: AnyActor
) -> list[CertificateTypeResponse]:
    """Return every certificate type."""
    kinds = await container.certificates.list_types.execute()
    return [CertificateTypeResponse.from_domain(k) for k in kinds]
