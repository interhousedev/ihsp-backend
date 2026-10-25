"""DELETE /v1/files/{id}: delete a file and report what used it."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.mapping import to_used_by
from app.interfaces.http.v1.files.schemas import DeleteFileResponse
from app.modules.files.domain.used_by import UsedBy
from app.shared.actor import Actor

from fastapi import Depends


async def delete_file(
    file_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> DeleteFileResponse:
    """Delete the caller's file; links and lessons that used it stop working."""
    used_by: list[UsedBy] = await container.files.delete_file.execute(actor, file_id)
    return DeleteFileResponse(used_by=to_used_by(used_by))
