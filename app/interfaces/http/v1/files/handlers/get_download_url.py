"""GET /v1/files/{id}/url: a download URL valid for 60 seconds."""

from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.schemas import DownloadUrlResponse
from app.modules.files.application.download_links import DownloadUrl
from app.shared.actor import Actor

from fastapi import Depends, Query


async def get_download_url(
    file_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    disposition: Annotated[Literal["inline", "attachment"] | None, Query()] = None,
) -> DownloadUrlResponse:
    """Presign a GET; only PDFs and images may be shown inline."""
    result: DownloadUrl = await container.files.get_download_url.execute(
        actor, file_id, disposition
    )
    return DownloadUrlResponse(url=result.url, expires_at=result.expires_at)
