"""POST /v1/admin/links/{id}/disable."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_moderation.moderation.schemas import DisableBody
from app.interfaces.http.v1.links.schemas import ModerationItem, moderation_item
from app.shared.actor import Actor, Role

from fastapi import Depends


async def disable_link(
    link_id: UUID,
    body: DisableBody,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> ModerationItem:
    """Disable a link, share or lesson resource with a reason (SL-8)."""
    view = await container.links.disable_link.execute(actor, link_id, body.reason)
    return moderation_item(view)
