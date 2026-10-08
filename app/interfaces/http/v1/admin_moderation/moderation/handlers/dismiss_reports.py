"""POST /v1/admin/links/{id}/dismiss-reports."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.links.schemas import ModerationItem, moderation_item
from app.shared.actor import Actor, Role

from fastapi import Depends


async def dismiss_reports(
    link_id: UUID,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> ModerationItem:
    """Remove a link from the moderation queue without disabling it."""
    view = await container.links.dismiss_reports.execute(actor, link_id)
    return moderation_item(view)
