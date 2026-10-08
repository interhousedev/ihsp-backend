"""Room page route (`ihsu.uz/r/{room}`)."""

from app.interfaces.http.public.rooms.handlers.open_room_page import open_room_page

from fastapi import APIRouter

router = APIRouter(prefix="/r")
router.add_api_route(
    "/{room_slug}", open_room_page, methods=["GET"], include_in_schema=False
)
