"""SQL repository for homework to-do rows."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.records import TodoRecord
from app.modules.academic.infrastructure.orm.homework_todo import HomeworkTodo
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _record(row: Any) -> TodoRecord:
    return TodoRecord(
        student_id=row.student_id,
        lesson_id=row.lesson_id,
        done_at=row.done_at,
        note=row.note,
        updated_at=row.updated_at,
    )


class SqlTodoRepository:
    """Implements TodoRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, student_id: UUID, lesson_id: UUID) -> TodoRecord | None:
        """Return the to-do row or None."""
        stmt = sa.select(
            HomeworkTodo.student_id,
            HomeworkTodo.lesson_id,
            HomeworkTodo.done_at,
            HomeworkTodo.note,
            HomeworkTodo.updated_at,
        ).where(
            HomeworkTodo.student_id == student_id, HomeworkTodo.lesson_id == lesson_id
        )
        row = (await self.session.execute(stmt)).first()
        return None if row is None else _record(row)

    async def _upsert(
        self,
        student_id: UUID,
        lesson_id: UUID,
        now: dt.datetime,
        values: dict[str, Any],
    ) -> TodoRecord:
        stmt = pg_insert(HomeworkTodo).values(
            id=new_id(),
            student_id=student_id,
            lesson_id=lesson_id,
            created_at=now,
            updated_at=now,
            **values,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[HomeworkTodo.student_id, HomeworkTodo.lesson_id],
            set_={**values, "updated_at": now},
        ).returning(
            HomeworkTodo.student_id,
            HomeworkTodo.lesson_id,
            HomeworkTodo.done_at,
            HomeworkTodo.note,
            HomeworkTodo.updated_at,
        )
        return _record((await self.session.execute(upsert)).one())

    async def upsert_done(
        self,
        student_id: UUID,
        lesson_id: UUID,
        done_at: dt.datetime | None,
        now: dt.datetime,
    ) -> TodoRecord:
        """Tick or untick; creates the row on first use."""
        return await self._upsert(student_id, lesson_id, now, {"done_at": done_at})

    async def upsert_note(
        self, student_id: UUID, lesson_id: UUID, note: str | None, now: dt.datetime
    ) -> TodoRecord:
        """Save or clear the note; creates the row on first use."""
        return await self._upsert(student_id, lesson_id, now, {"note": note})
