"""GET /v1/admin/moderation/search."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.links.schemas import ModerationItem, moderation_item
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def search(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    q: Annotated[str, Query(min_length=1, max_length=300)],
) -> list[ModerationItem]:
    """Find links by short ID, share URL or owner login (ADM-13)."""
    views = await container.links.search_moderation.execute(actor, q)
    return [moderation_item(view) for view in views]
