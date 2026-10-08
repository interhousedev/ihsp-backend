"""SQL repository of timetable entries."""

from uuid import UUID

from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.modules.academic.infrastructure.orm import TimetableEntry as EntryRow
from app.modules.academic.infrastructure.schedule.array_ops import overlaps
from app.modules.academic.infrastructure.schedule.mappers import (
    entry_apply,
    entry_new_row,
    entry_to_entity,
)

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class SqlTimetableEntryRepository:
    """Timetable entries in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, entry_id: UUID) -> TimetableEntry | None:
        """Return the entry or None."""
        row = await self.session.get(EntryRow, entry_id)
        return entry_to_entity(row) if row else None

    async def add(self, entry: TimetableEntry) -> None:
        """Insert an entry."""
        self.session.add(entry_new_row(entry))
        await self.session.flush()

    async def save(self, entry: TimetableEntry) -> None:
        """Write the changes of an entry."""
        row = await self.session.get(EntryRow, entry.id)
        if row is None:
            return
        entry_apply(row, entry)
        await self.session.flush()

    async def delete(self, entry_id: UUID) -> None:
        """Delete an entry."""
        row = await self.session.get(EntryRow, entry_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def list_for_term(self, term_id: UUID) -> list[TimetableEntry]:
        """Return every entry of the term."""
        rows = await self.session.scalars(
            select(EntryRow).where(EntryRow.term_id == term_id)
        )
        return [entry_to_entity(row) for row in rows]

    async def search(
        self,
        term_id: UUID,
        *,
        group_id: UUID | None = None,
        teacher_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> list[TimetableEntry]:
        """Return the term's entries of a group, a teacher or a room."""
        stmt = select(EntryRow).where(EntryRow.term_id == term_id)
        if group_id is not None:
            keys = [str(group_id), f"{group_id}:1", f"{group_id}:2"]
            stmt = stmt.where(overlaps(EntryRow.audience, keys))
        if teacher_id is not None:
            stmt = stmt.where(EntryRow.teacher_id == teacher_id)
        if room_id is not None:
            stmt = stmt.where(EntryRow.room_id == room_id)
        return [entry_to_entity(row) for row in await self.session.scalars(stmt)]

    async def same_slot(
        self, term_id: UUID, weekday: int, period: int
    ) -> list[TimetableEntry]:
        """Return entries of the term at one weekday and period."""
        stmt = select(EntryRow).where(
            EntryRow.term_id == term_id,
            EntryRow.weekday == weekday,
            EntryRow.period == period,
        )
        return [entry_to_entity(row) for row in await self.session.scalars(stmt)]

    async def clear_teacher(self, teacher_id: UUID) -> int:
        """Set teacher_id to NULL on the teacher's entries; return how many."""
        result = await self.session.execute(
            update(EntryRow)
            .where(EntryRow.teacher_id == teacher_id)
            .values(teacher_id=None)
            .returning(EntryRow.id)
        )
        return len(result.all())

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move entries from one room to another; return how many."""
        result = await self.session.execute(
            update(EntryRow)
            .where(EntryRow.room_id == source_id)
            .values(room_id=target_id)
            .returning(EntryRow.id)
        )
        return len(result.all())
