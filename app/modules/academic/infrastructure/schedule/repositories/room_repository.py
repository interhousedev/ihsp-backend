"""SQL repository of rooms."""

from collections.abc import Collection
from uuid import UUID

from app.modules.academic.domain.schedule.errors import RoomSlugTakenError
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.infrastructure.orm import Room as RoomRow
from app.modules.academic.infrastructure.schedule.mappers import (
    room_apply,
    room_new_row,
    room_to_entity,
)

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class SqlRoomRepository:
    """Rooms in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, room_id: UUID) -> Room | None:
        """Return the room or None."""
        row = await self.session.get(RoomRow, room_id)
        return room_to_entity(row) if row else None

    async def get_many(self, room_ids: Collection[UUID]) -> dict[UUID, Room]:
        """Return the rooms that exist, by id."""
        if not room_ids:
            return {}
        rows = await self.session.scalars(
            select(RoomRow).where(RoomRow.id.in_(list(room_ids)))
        )
        return {row.id: room_to_entity(row) for row in rows}

    async def get_by_slug(self, slug: str) -> Room | None:
        """Return the room with this slug (any status)."""
        stmt = select(RoomRow).where(RoomRow.slug == slug)
        row = (await self.session.scalars(stmt.limit(1))).first()
        return room_to_entity(row) if row else None

    async def add(self, room: Room) -> None:
        """Insert a room."""
        self.session.add(room_new_row(room))
        await self._flush(room.slug)

    async def save(self, room: Room) -> None:
        """Write the changes of a room."""
        row = await self.session.get(RoomRow, room.id)
        if row is None:
            return
        room_apply(row, room)
        await self._flush(room.slug)

    async def _flush(self, slug: str) -> None:
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise RoomSlugTakenError(params={"slug": slug}) from error

    async def list_all(self, status: str | None = None) -> list[Room]:
        """Return rooms ordered by name, optionally of one status."""
        stmt = select(RoomRow).order_by(RoomRow.name)
        if status is not None:
            stmt = stmt.where(RoomRow.status == status)
        return [room_to_entity(row) for row in await self.session.scalars(stmt)]
