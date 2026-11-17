"""SQLAlchemy repository of the memory notes."""

from typing import cast
from uuid import UUID

from app.modules.admission.domain.memory_notes import MemoryNote, NoteSource
from app.modules.admission.infrastructure.orm.memory_notes import MemoryNoteRow

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _note(row: MemoryNoteRow) -> MemoryNote:
    return MemoryNote(
        id=row.id,
        student_id=row.student_id,
        content=row.content,
        source=cast(NoteSource, row.source),
        created_at=row.created_at,
    )


class SqlMemoryNoteRepository:
    """MemoryNoteRepository over `admission.memory_notes`."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[MemoryNote]:
        """Return the student's notes, newest first."""
        rows = await self._s.scalars(
            select(MemoryNoteRow)
            .where(MemoryNoteRow.student_id == student_id)
            .order_by(MemoryNoteRow.created_at.desc(), MemoryNoteRow.id.desc())
        )
        return [_note(r) for r in rows]

    async def count_for(self, student_id: UUID) -> int:
        """Return how many notes the student has."""
        total = await self._s.scalar(
            select(func.count())
            .select_from(MemoryNoteRow)
            .where(MemoryNoteRow.student_id == student_id)
        )
        return int(total or 0)

    async def get(self, note_id: UUID) -> MemoryNote | None:
        """Return one note."""
        row = await self._s.get(MemoryNoteRow, note_id)
        return _note(row) if row else None

    async def add(self, note: MemoryNote) -> None:
        """Insert a note."""
        self._s.add(
            MemoryNoteRow(
                id=note.id,
                student_id=note.student_id,
                content=note.content,
                source=note.source,
                created_at=note.created_at,
            )
        )
        await self._s.flush()

    async def delete(self, note_id: UUID) -> None:
        """Delete a note."""
        await self._s.execute(delete(MemoryNoteRow).where(MemoryNoteRow.id == note_id))
