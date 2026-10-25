"""POST /v1/links."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.links.links.schemas import CreateLinkBody
from app.interfaces.http.v1.links.schemas import LinkItem, link_item
from app.modules.links.domain.link import LinkKind
from app.shared.actor import Actor

from fastapi import Depends


async def create_link(
    body: CreateLinkBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LinkItem:
    """Shorten a URL or publish one of the caller's files (SL-1)."""
    view = await container.links.create_link.execute(
        actor,
        kind=LinkKind(body.kind),
        target_url=body.target_url,
        file_id=body.file_id,
    )
    return link_item(view)
