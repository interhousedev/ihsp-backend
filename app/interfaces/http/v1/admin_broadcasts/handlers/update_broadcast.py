"""PATCH /v1/admin/broadcasts/{broadcast_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import (
    BroadcastPatchBody,
    BroadcastResponse,
)
from app.modules.admin.application.update_broadcast import BroadcastPatch


async def update_broadcast(
    broadcast_id: UUID,
    body: BroadcastPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> BroadcastResponse:
    """Edit a draft or scheduled broadcast."""
    patch = BroadcastPatch(
        title=body.title,
        text=body.text,
        media_file_ids=body.media_file_ids,
        audience=body.audience.to_domain() if body.audience else None,
    )
    view = await container.admin.update_broadcast.execute(actor, broadcast_id, patch)
    return BroadcastResponse.from_view(view)
