"""PATCH /v1/files/{id}: rename a file."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.mapping import to_file_item
from app.interfaces.http.v1.files.schemas import FileItem, RenameFileBody
from app.modules.files.application.file_views import FileView
from app.shared.actor import Actor

from fastapi import Depends


async def rename_file(
    file_id: UUID,
    body: RenameFileBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> FileItem:
    """Change the name of the caller's file."""
    view: FileView = await container.files.rename_file.execute(
        actor, file_id, body.name
    )
    return to_file_item(view)
