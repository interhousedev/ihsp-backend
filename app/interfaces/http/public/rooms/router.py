"""Room page routes (`ihsu.uz/r/{room}`)."""

from app.interfaces.http.public.rooms.handlers.open_room_page import (
    open_room_page,
    submit_room_pin,
)

from fastapi import APIRouter

router = APIRouter(prefix="/r")
router.add_api_route(
    "/{room_slug}", open_room_page, methods=["GET"], include_in_schema=False
)
router.add_api_route(
    "/{room_slug}", submit_room_pin, methods=["POST"], include_in_schema=False
)
