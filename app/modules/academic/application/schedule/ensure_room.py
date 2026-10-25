"""Find or create a room from a typed name (ROOM-1)."""

import datetime as dt

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.room import (
    Room,
    clean_room_name,
    room_slug,
)
from app.shared.clock import Clock
from app.shared.ids import new_id, random_digits

PIN_LENGTH = 6
MAX_MERGE_HOPS = 10


async def ensure_room_in(uow: ScheduleUnitOfWork, name: str, now: dt.datetime) -> Room:
    """Return the room for a name inside an open transaction, creating it if new.

    A merged room leads to the room it was merged into; an archived room is
    reopened because someone uses its name again.
    """
    clean = clean_room_name(name)
    slug = room_slug(clean)
    existing = await uow.rooms.get_by_slug(slug)
    if existing is None:
        room = Room(
            id=new_id(),
            slug=slug,
            name=clean,
            pin=random_digits(PIN_LENGTH),
            pin_changed_at=now,
        )
        await uow.rooms.add(room)
        return room
    room = await _follow_merges(uow, existing)
    if room.status == "archived":
        room.status = "active"
        room.merged_into_id = None
        await uow.rooms.save(room)
    return room


async def find_room_in(uow: ScheduleUnitOfWork, name: str) -> Room | None:
    """Return the room a name leads to without creating or reopening anything."""
    slug = room_slug(clean_room_name(name))
    existing = await uow.rooms.get_by_slug(slug)
    return await _follow_merges(uow, existing) if existing else None


async def _follow_merges(uow: ScheduleUnitOfWork, room: Room) -> Room:
    for _ in range(MAX_MERGE_HOPS):
        if room.merged_into_id is None:
            return room
        target = await uow.rooms.get(room.merged_into_id)
        if target is None:
            return room
        room = target
    return room


class EnsureRoom:
    """Find or create a room by name in its own transaction."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, name: str) -> Room:
        """Return the active room for the name; new rooms get a random PIN."""
        async with self.uow_factory() as uow:
            room = await ensure_room_in(uow, name, self.clock.now())
            await uow.commit()
        return room
