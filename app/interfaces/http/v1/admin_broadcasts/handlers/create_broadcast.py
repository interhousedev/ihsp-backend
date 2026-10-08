"""POST /v1/admin/broadcasts."""

from app.interfaces.http.v1.admin_broadcasts.dependencies import (
    AdminActor,
    ContainerDep,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import (
    BroadcastInputBody,
    BroadcastResponse,
)


async def create_broadcast(
    body: BroadcastInputBody, container: ContainerDep, actor: AdminActor
) -> BroadcastResponse:
    """Create a draft broadcast."""
    view = await container.admin.create_broadcast.execute(
        actor,
        title=body.title,
        text=body.text,
        media_file_ids=body.media_file_ids,
        audience=body.audience.to_domain(),
    )
    return BroadcastResponse.from_view(view)
