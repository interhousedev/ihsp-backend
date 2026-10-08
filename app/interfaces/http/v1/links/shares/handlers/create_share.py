"""POST /v1/shares."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.schemas import LinkItem, link_item
from app.interfaces.http.v1.links.shares.schemas import CreateShareBody
from app.modules.links.domain.link import LinkKind, ShareMode
from app.shared.actor import Actor

from fastapi import Depends


async def create_share(
    body: CreateShareBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LinkItem:
    """Create a public share of the caller's chat or flash card set (SHR-1)."""
    view = await container.links.create_share.execute(
        actor,
        kind=LinkKind(body.kind),
        target_id=body.target_id,
        share_mode=ShareMode(body.share_mode) if body.share_mode else None,
        expires_at=body.expires_at,
    )
    return link_item(view)
