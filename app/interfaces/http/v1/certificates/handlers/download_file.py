"""GET /v1/certificates/files/{file_id}/download."""

from uuid import UUID

from app.interfaces.http.v1.certificates.deps import AnyActor, ContainerDep

from fastapi import status
from fastapi.responses import RedirectResponse


async def download_file(
    file_id: UUID, container: ContainerDep, actor: AnyActor
) -> RedirectResponse:
    """Redirect to a short-lived download URL of an attached file."""
    url = await container.certificates.get_file_download.execute(actor, file_id)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
