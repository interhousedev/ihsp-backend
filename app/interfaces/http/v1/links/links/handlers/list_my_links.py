"""GET /v1/me/links."""

from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.links.schemas import LinkPageResponse
from app.interfaces.http.v1.links.schemas import link_item
from app.modules.links.domain.link import LinkKind
from app.shared.actor import Actor

from fastapi import Depends, Query


async def list_my_links(
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    kind: (
        Literal["url", "file", "chat", "flashcard_set", "artifact", "message"] | None
    ) = None,
    target_id: UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LinkPageResponse:
    """List the caller's links, filtered by kind (SL-7, SHR-6)."""
    page = await container.links.list_my_links.execute(
        actor,
        kind=LinkKind(kind) if kind else None,
        target_id=target_id,
        cursor=cursor,
        limit=limit,
    )
    return LinkPageResponse(
        items=[link_item(view) for view in page.items], next_cursor=page.next_cursor
    )
