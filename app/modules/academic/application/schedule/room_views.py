"""Building Room read models with the page URL and this week's lessons."""

import datetime as dt
from collections.abc import Sequence

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import RoomData
from app.modules.academic.domain.schedule.calendar import monday_of
from app.modules.academic.domain.schedule.room import Room


def room_url(base_url: str, room: Room) -> str:
    """Return the room page address with its PIN (ROOM-2)."""
    return f"{base_url.rstrip('/')}/{room.slug}?pin={room.pin}"


async def build_room_data(
    uow: ScheduleUnitOfWork, rooms: Sequence[Room], *, today: dt.date, base_url: str
) -> list[RoomData]:
    """Return rooms with the number of lessons in the current ISO week."""
    monday = monday_of(today)
    counts = await uow.lessons.count_by_room(monday, monday + dt.timedelta(days=6))
    return [
        RoomData(
            id=room.id,
            slug=room.slug,
            name=room.name,
            pin=room.pin,
            url=room_url(base_url, room),
            status=room.status,
            lessons_this_week=counts.get(room.id, 0),
        )
        for room in rooms
    ]
