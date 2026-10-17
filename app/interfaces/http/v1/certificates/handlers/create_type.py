"""POST /v1/certificates/admin/types."""

from app.interfaces.http.v1.certificates.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.certificates.schemas import (
    CertificateTypeInput,
    CertificateTypeResponse,
)


async def create_type(
    body: CertificateTypeInput, container: ContainerDep, actor: AdminActor
) -> CertificateTypeResponse:
    """Create a custom certificate type."""
    fields = body.model_dump(exclude_unset=True)
    kind = await container.certificates.create_type.execute(fields)
    return CertificateTypeResponse.from_domain(kind)
