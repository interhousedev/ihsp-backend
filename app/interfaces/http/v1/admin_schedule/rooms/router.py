"""Router of /v1/admin/rooms."""

from app.interfaces.http.v1.admin_schedule.rooms.handlers.archive_room import (
    archive_room,
)
from app.interfaces.http.v1.admin_schedule.rooms.handlers.list_rooms import list_rooms
from app.interfaces.http.v1.admin_schedule.rooms.handlers.merge_room import merge_room
from app.interfaces.http.v1.admin_schedule.rooms.handlers.regenerate_pin import (
    regenerate_pin,
)
from app.interfaces.http.v1.admin_schedule.rooms.handlers.rename_room import (
    rename_room,
)
from app.interfaces.http.v1.admin_schedule.rooms.schemas import RoomResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/rooms", tags=["admin-schedule"])
router.add_api_route("", list_rooms, methods=["GET"], response_model=list[RoomResponse])
router.add_api_route(
    "/{room_id}", rename_room, methods=["PATCH"], response_model=RoomResponse
)
router.add_api_route(
    "/{room_id}/regenerate-pin",
    regenerate_pin,
    methods=["POST"],
    response_model=RoomResponse,
)
router.add_api_route(
    "/{room_id}/merge", merge_room, methods=["POST"], response_model=RoomResponse
)
router.add_api_route(
    "/{room_id}/archive", archive_room, methods=["POST"], response_model=RoomResponse
)
