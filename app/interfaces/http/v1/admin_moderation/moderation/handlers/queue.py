"""GET /v1/admin/moderation/queue."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_moderation.moderation.schemas import (
    ModerationPageResponse,
)
from app.interfaces.http.v1.links.schemas import moderation_item
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def queue(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ModerationPageResponse:
    """List reported links, most reported first (UF-ADM-10)."""
    page = await container.links.list_moderation_queue.execute(
        actor, cursor=cursor, limit=limit
    )
    return ModerationPageResponse(
        items=[moderation_item(view) for view in page.items],
        next_cursor=page.next_cursor,
    )
