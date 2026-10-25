"""GET /v1/admin/rooms."""

from typing import Annotated, Literal

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.rooms.schemas import RoomResponse

from fastapi import Query


async def list_rooms(
    container: ContainerDep,
    actor: AdminActor,
    status: Annotated[Literal["active", "archived"] | None, Query()] = None,
) -> list[RoomResponse]:
    """List rooms with their links, PINs and lessons this week."""
    rooms = await container.academic.schedule.list_rooms.execute(status)
    return [RoomResponse.model_validate(room) for room in rooms]
