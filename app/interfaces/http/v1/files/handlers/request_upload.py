"""POST /v1/files: start an upload."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.mapping import to_upload_response
from app.interfaces.http.v1.files.schemas import RequestUploadBody, UploadResponse
from app.modules.files.application.request_upload import UploadTicket
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose

from fastapi import Depends


async def request_upload(
    body: RequestUploadBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> UploadResponse:
    """Check type, size and quota, create a pending file and a presigned PUT."""
    ticket: UploadTicket = await container.files.request_upload.execute(
        actor,
        name=body.name,
        size=body.size,
        content_type=body.content_type,
        sha256_b64=body.sha256_b64,
        purpose=FilePurpose(body.purpose),
    )
    return to_upload_response(ticket)
