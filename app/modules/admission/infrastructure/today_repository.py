"""SQLAlchemy repository of the Today feed."""

import datetime as dt
from collections.abc import Collection
from typing import cast
from uuid import UUID

from app.modules.admission.domain.today import Pin, SeasonKey
from app.modules.admission.infrastructure.orm.today import (
    ActivityDayRow,
    SeasonOverrideRow,
    StaffPinRow,
    TodaySnoozeRow,
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

    async def snoozes(self, student_id: UUID) -> dict[str, tuple[int, dt.date]]:
        """Per action key: how often it was snoozed and until which day."""
        rows = await self._s.execute(
            select(
                TodaySnoozeRow.key, TodaySnoozeRow.count, TodaySnoozeRow.until
            ).where(TodaySnoozeRow.student_id == student_id)
        )
        return {k: (c, u) for k, c, u in rows.all()}

    async def save_snooze(
        self, student_id: UUID, key: str, count: int, until: dt.date
    ) -> None:
        """Insert or replace the snooze of one action."""
        stmt = insert(TodaySnoozeRow).values(
            student_id=student_id, key=key, count=count, until=until
        )
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id", "key"],
                set_={"count": count, "until": until, "updated_at": func.now()},
            )
        )

    async def pin(self, student_id: UUID) -> Pin | None:
        """The stored pin of the student (expired ones included)."""
        r = await self._s.get(StaffPinRow, student_id)
        if r is None:
            return None
        return Pin(
            r.student_id,
            r.title,
            r.href,
            r.note,
            r.pinned_by,
            r.pinned_by_name,
            r.expires_at,
        )

    async def set_pin(self, pin: Pin) -> None:
        """Insert or replace the student's pin."""
        values = {
            "title": pin.title,
            "href": pin.href,
            "note": pin.note,
            "pinned_by": pin.pinned_by,
            "pinned_by_name": pin.pinned_by_name,
            "expires_at": pin.expires_at,
        }
        stmt = insert(StaffPinRow).values(student_id=pin.student_id, **values)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"],
                set_={**values, "updated_at": func.now()},
            )
        )

    async def clear_pin(self, student_id: UUID) -> bool:
        """Remove the pin; return whether there was one."""
        result = await self._s.execute(
            delete(StaffPinRow).where(StaffPinRow.student_id == student_id)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]
