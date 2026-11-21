"""SQLAlchemy repository of the Today feed."""

import datetime as dt
from collections.abc import Collection
from typing import cast
from uuid import UUID

from app.modules.admission.domain.today import SeasonKey
from app.modules.admission.infrastructure.orm.today import (
    ActivityDayRow,
    SeasonOverrideRow,
)

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlTodayRepository:
    """Activity days and season overrides."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def activity_days(self, student_id: UUID, since: dt.date) -> set[dt.date]:
        """Days on or after `since` on which the student did something."""
        rows = await self._s.execute(
            select(ActivityDayRow.day).where(
                ActivityDayRow.student_id == student_id, ActivityDayRow.day >= since
            )
        )
        return set(rows.scalars())

    async def touch(self, student_ids: Collection[UUID], day: dt.date) -> None:
        """Record `day` as active for each student (idempotent)."""
        if not student_ids:
            return
        await self._s.execute(
            insert(ActivityDayRow)
            .values([{"student_id": s, "day": day} for s in student_ids])
            .on_conflict_do_nothing()
        )

    async def season_override(self, student_id: UUID) -> SeasonKey | None:
        """The season the student fixed, if any."""
        row = await self._s.get(SeasonOverrideRow, student_id)
        return cast(SeasonKey, row.key) if row is not None else None

    async def set_season_override(
        self, student_id: UUID, key: SeasonKey | None
    ) -> None:
        """Fix a season, or None to go back to the automatic one."""
        if key is None:
            await self._s.execute(
                delete(SeasonOverrideRow).where(
                    SeasonOverrideRow.student_id == student_id
                )
            )
            return
        stmt = insert(SeasonOverrideRow).values(student_id=student_id, key=key)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"],
                set_={"key": key, "updated_at": func.now()},
            )
        )
