"""GET /v1/me/files: the caller's files."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.files.mapping import to_file_item
from app.interfaces.http.v1.files.schemas import FileItem
from app.modules.files.application.list_my_files import FilePage
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from app.shared.pagination import Page

from fastapi import Depends, Query


async def list_my_files(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    purpose: Annotated[FilePurpose | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[FileItem]:
    """Return one page of files, newest first."""
    page: FilePage = await container.files.list_my_files.execute(
        actor, purpose=purpose, cursor=cursor, limit=limit
    )
    return Page[FileItem](
        items=[to_file_item(view) for view in page.items],
        next_cursor=page.next_cursor,
    )
