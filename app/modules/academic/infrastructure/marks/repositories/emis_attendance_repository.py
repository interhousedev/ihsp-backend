"""SQL repository of attendance read from EMIS."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.infrastructure.orm.emis_attendance import EmisAttendance

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlEmisAttendanceRepository:
    """Implements EmisAttendanceRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def save(
        self,
        student_id: UUID,
        subject_id: UUID,
        semester: int,
        *,
        absent_dates: Sequence[dt.date] | None,
        absence_total: int | None,
        at: dt.datetime,
    ) -> None:
        """Insert or replace one subject's EMIS attendance."""
        dates = None if absent_dates is None else sorted(set(absent_dates))
        stmt = insert(EmisAttendance).values(
            student_id=student_id,
            subject_id=subject_id,
            semester=semester,
            absent_dates=dates,
            absence_total=absence_total,
            synced_at=at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["student_id", "subject_id", "semester"],
            set_={
                "absent_dates": stmt.excluded.absent_dates,
                "absence_total": stmt.excluded.absence_total,
                "synced_at": stmt.excluded.synced_at,
                "updated_at": func.now(),
            },
        )
        await self.session.execute(stmt)
