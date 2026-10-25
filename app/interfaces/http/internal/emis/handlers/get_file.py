"""GET /internal/emis/{user_id}/file?url=&max_bytes=: a material EMIS links."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container

from fastapi import Depends, Query, Response

FILE_NAME_HEADER = "X-Emis-File-Name"
MAX_BYTES_LIMIT = 1024 * 1024 * 1024


async def get_file(
    user_id: UUID,
    url: Annotated[str, Query(min_length=8, max_length=2048)],
    max_bytes: Annotated[int, Query(ge=1, le=MAX_BYTES_LIMIT)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Download the file with the student's EMIS session and pass the bytes on."""
    file = await container.identity.emis.gateway.download(
        user_id, url, max_bytes=max_bytes
    )
    return Response(
        content=file.data,
        media_type=file.content_type or "application/octet-stream",
        headers={FILE_NAME_HEADER: quote(file.name, safe="")},
    )
