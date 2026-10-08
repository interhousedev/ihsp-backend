"""POST /v1/links/{id}/revoke."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.schemas import LinkItem, link_item
from app.shared.actor import Actor

from fastapi import Depends


async def revoke_link(
    link_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LinkItem:
    """Revoke a share (SHR-6)."""
    return link_item(await container.links.revoke_link.execute(actor, link_id))
