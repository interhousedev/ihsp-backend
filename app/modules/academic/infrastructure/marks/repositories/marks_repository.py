"""SQL repository of marks written by the sync."""

import datetime as dt
from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.academic.domain.marks.diff import MarkKey
from app.modules.academic.domain.marks.records import NewMark, StoredMark
from app.modules.academic.infrastructure.orm.mark import Mark
from app.shared.contracts.emis import EmisMarkType
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


class SqlMarksRepository:
    """Implements MarksRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def list_for_subject(
        self, student_id: UUID, subject_id: UUID, semester: int
    ) -> list[StoredMark]:
        """Return stored marks of one subject and semester, removed ones too."""
        stmt = sa.select(
            Mark.id,
            Mark.type,
            Mark.date,
            Mark.value,
            Mark.ordinal,
            Mark.lesson_id,
            Mark.removed_at,
        ).where(
            Mark.student_id == student_id,
            Mark.subject_id == subject_id,
            Mark.semester == semester,
        )
        return [
            StoredMark(
                id=r.id,
                key=MarkKey(EmisMarkType(r.type), r.date, r.value, r.ordinal),
                removed=r.removed_at is not None,
                lesson_id=r.lesson_id,
            )
            for r in (await self.session.execute(stmt)).all()
        ]

    async def add(self, marks: Sequence[NewMark]) -> None:
        """Insert new marks."""
        if not marks:
            return
        await self.session.execute(
            sa.insert(Mark),
            [
                {
                    "id": new_id(),
                    "student_id": m.student_id,
                    "subject_id": m.subject_id,
                    "semester": m.semester,
                    "type": m.key.type.value,
                    "value": m.key.value,
                    "date": m.key.date,
                    "ordinal": m.key.ordinal,
                    "lesson_id": m.lesson_id,
                }
                for m in marks
            ],
        )

    async def set_removed(
        self, mark_ids: Collection[UUID], removed_at: dt.datetime | None
    ) -> None:
        """Mark rows removed (a moment) or restored (None)."""
        if not mark_ids:
            return
        await self.session.execute(
            sa.update(Mark)
            .where(Mark.id.in_(list(mark_ids)))
            .values(removed_at=removed_at)
        )

    async def values_by_type(
        self, student_id: UUID, subject_id: UUID, semester: int
    ) -> dict[str, list[int]]:
        """Return non-removed mark values of a subject grouped by type."""
        stmt = sa.select(Mark.type, Mark.value).where(
            Mark.student_id == student_id,
            Mark.subject_id == subject_id,
            Mark.semester == semester,
            Mark.removed_at.is_(None),
        )
        grouped: dict[str, list[int]] = {}
        for row in (await self.session.execute(stmt)).all():
            grouped.setdefault(row.type, []).append(row.value)
        return grouped

    async def semester_values(self, student_id: UUID, semester: int) -> list[int]:
        """Return all non-removed mark values of the semester."""
        stmt = sa.select(Mark.value).where(
            Mark.student_id == student_id,
            Mark.semester == semester,
            Mark.removed_at.is_(None),
        )
        return list((await self.session.execute(stmt)).scalars())
