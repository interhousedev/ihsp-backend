"""PATCH /v1/certificates/admin/types/{type_id}."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.certificates.schemas import (
    CertificateTypePatch,
    CertificateTypeResponse,
)


async def update_type(
    type_id: UUID,
    body: CertificateTypePatch,
    container: ContainerDep,
    actor: AdminActor,
) -> CertificateTypeResponse:
    """Change the sent fields of a type."""
    changes = body.model_dump(exclude_unset=True)
    kind = await container.certificates.update_type.execute(type_id, changes)
    return CertificateTypeResponse.from_domain(kind)
