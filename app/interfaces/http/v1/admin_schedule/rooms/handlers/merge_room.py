"""POST /v1/admin/rooms/{id}/merge."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.rooms.schemas import (
    RoomMergeBody,
    RoomResponse,
)


async def merge_room(
    room_id: UUID, body: RoomMergeBody, container: ContainerDep, actor: AdminActor
) -> RoomResponse:
    """Merge the room into another and return the target."""
    room = await container.academic.schedule.merge_room.execute(
        room_id, body.into_room_id
    )
    return RoomResponse.model_validate(room)
