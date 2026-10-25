"""GET /v1/files/{id}: file metadata."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.mapping import to_file_item
from app.interfaces.http.v1.files.schemas import FileItem
from app.modules.files.application.file_views import FileView
from app.shared.actor import Actor

from fastapi import Depends


async def get_file(
    file_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> FileItem:
    """Return the file to its owner or an administrator."""
    view: FileView = await container.files.get_file.execute(actor, file_id)
    return to_file_item(view)
