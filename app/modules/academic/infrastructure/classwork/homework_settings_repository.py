"""SQL repository for teachers' homework defaults."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.records import TeacherHomeworkSettings
from app.modules.academic.infrastructure.orm.teacher_homework_settings import (
    TeacherHomeworkSettings as SettingsRow,
)

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _record(row: Any) -> TeacherHomeworkSettings:
    return TeacherHomeworkSettings(
        teacher_id=row.teacher_id,
        accept_by_default=row.accept_by_default,
        notify_on_submission=row.notify_on_submission,
    )


class SqlHomeworkSettingsRepository:
    """Implements HomeworkSettingsRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, teacher_id: UUID) -> TeacherHomeworkSettings:
        """The teacher's settings (the defaults when nothing was saved)."""
        found = await self.get_many([teacher_id])
        return found.get(teacher_id, TeacherHomeworkSettings(teacher_id))

    async def get_many(
        self, teacher_ids: Sequence[UUID]
    ) -> dict[UUID, TeacherHomeworkSettings]:
        """Saved settings by teacher; teachers without a row are absent."""
        if not teacher_ids:
            return {}
        stmt = sa.select(SettingsRow).where(SettingsRow.teacher_id.in_(teacher_ids))
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.teacher_id: _record(row) for row in rows}

    async def save(
        self,
        teacher_id: UUID,
        *,
        accept_by_default: bool | None,
        notify_on_submission: bool | None,
        now: dt.datetime,
    ) -> TeacherHomeworkSettings:
        """Create or update the row; ``None`` keeps a field."""
        current = await self.get(teacher_id)
        accept = (
            current.accept_by_default
            if accept_by_default is None
            else accept_by_default
        )
        notify = (
            current.notify_on_submission
            if notify_on_submission is None
            else notify_on_submission
        )
        values = {"accept_by_default": accept, "notify_on_submission": notify}
        stmt = (
            pg_insert(SettingsRow)
            .values(teacher_id=teacher_id, created_at=now, updated_at=now, **values)
            .on_conflict_do_update(
                index_elements=[SettingsRow.teacher_id],
                set_={**values, "updated_at": now},
            )
        )
        await self.session.execute(stmt)
        return TeacherHomeworkSettings(teacher_id, accept, notify)
