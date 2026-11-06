"""GET /v1/certificates/files/{file_id}/download-url."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import AnyActor, ContainerDep
from app.interfaces.http.v1.certificates.schemas import CertificateFileUrl


async def get_file_url(
    file_id: UUID, container: ContainerDep, actor: AnyActor
) -> CertificateFileUrl:
    """Return a short-lived address, for clients that cannot follow a redirect."""
    url = await container.certificates.get_file_download.execute(actor, file_id)
    return CertificateFileUrl(url=url)
