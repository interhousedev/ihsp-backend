"""SQL repository of students' sync fields and curriculum."""

import datetime as dt
from typing import Any, Literal, cast
from uuid import UUID

from app.modules.academic.domain.marks.sync import StudentSyncState, SyncSubject
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_FAILURES = 32000


class SqlStudentSyncRepository:
    """Implements StudentSyncRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def lock(self, user_id: UUID) -> None:
        """Take a transaction-level advisory lock for the student."""
        key = sa.func.hashtextextended(f"marks-sync:{user_id}", 0)
        await self.session.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))

    async def get_state(self, user_id: UUID) -> StudentSyncState | None:
        """Return the student's sync state or None."""
        stmt = (
            sa.select(
                Student.user_id,
                Student.group_id,
                Student.subgroup,
                Student.status,
                Student.backfilled_at,
                Group.current_semester,
                Group.subject_ids,
            )
            .join(Group, Group.id == Student.group_id)
            .where(Student.user_id == user_id)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        return StudentSyncState(
            user_id=row.user_id,
            group_id=row.group_id,
            subgroup=row.subgroup,
            status=cast(Literal["active", "left"], row.status),
            backfilled_at=row.backfilled_at,
            current_semester=row.current_semester,
            subjects=await self._subjects(list(row.subject_ids or [])),
        )

    async def _subjects(self, subject_ids: list[UUID]) -> tuple[SyncSubject, ...]:
        """Return the curriculum subjects that EMIS knows."""
        if not subject_ids:
            return ()
        stmt = (
            sa.select(Subject.id, Subject.emis_subject_id, Subject.name)
            .where(Subject.id.in_(subject_ids), Subject.emis_subject_id.is_not(None))
            .order_by(Subject.emis_subject_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return tuple(
            SyncSubject(
                subject_id=r.id, emis_subject_id=r.emis_subject_id, name=dict(r.name)
            )
            for r in rows
        )

    async def list_sync_candidates(self) -> list[UUID]:
        """Return active students whose backfill is done."""
        stmt = (
            sa.select(Student.user_id)
            .where(Student.status == "active", Student.backfilled_at.is_not(None))
            .order_by(Student.user_id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def record_success(
        self, user_id: UUID, *, at: dt.datetime, backfilled: bool
    ) -> None:
        """Set synced_at, clear failures and (for a backfill) set backfilled_at."""
        values: dict[str, Any] = {
            "synced_at": at,
            "sync_failures": 0,
            "sync_error": None,
        }
        if backfilled:
            values["backfilled_at"] = at
        await self.session.execute(
            sa.update(Student).where(Student.user_id == user_id).values(**values)
        )

    async def record_failure(self, user_id: UUID, *, error: str) -> None:
        """Count one more consecutive failure and keep the error text."""
        failures = sa.func.least(Student.sync_failures + 1, _MAX_FAILURES)
        await self.session.execute(
            sa.update(Student)
            .where(Student.user_id == user_id)
            .values(sync_failures=failures, sync_error=error)
        )

    async def touch_profile_synced(self, user_id: UUID, *, at: dt.datetime) -> None:
        """Remember when the profile was refreshed."""
        await self.session.execute(
            sa.update(Student)
            .where(Student.user_id == user_id)
            .values(profile_synced_at=at)
        )

    async def sync_failures(self, user_id: UUID) -> int:
        """Return the student's consecutive failed syncs (0 for an unknown student)."""
        stmt = sa.select(Student.sync_failures).where(Student.user_id == user_id)
        return int(await self.session.scalar(stmt) or 0)
