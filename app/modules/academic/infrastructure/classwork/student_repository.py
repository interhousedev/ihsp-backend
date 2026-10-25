"""SQL repository for students and their groups."""

from collections.abc import Sequence
from typing import Any, Literal, cast
from uuid import UUID

from app.modules.academic.domain.classwork.records import StudentRecord
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.student import Student

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def _select() -> sa.Select[Any]:
    return sa.select(
        Student.user_id,
        Student.group_id,
        Group.name.label("group_name"),
        Student.subgroup,
        Student.status,
        Student.synced_at,
        Group.current_semester,
    ).join(Group, Group.id == Student.group_id)


def _record(row: Any) -> StudentRecord:
    return StudentRecord(
        user_id=row.user_id,
        group_id=row.group_id,
        group_name=row.group_name,
        subgroup=row.subgroup,
        status=cast(Literal["active", "left"], row.status),
        synced_at=row.synced_at,
        current_semester=row.current_semester,
    )


class SqlStudentRepository:
    """Implements StudentRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, user_id: UUID) -> StudentRecord | None:
        """Return the student or None."""
        rows = await self.by_ids([user_id])
        return rows[0] if rows else None

    async def active_in_groups(self, group_ids: Sequence[UUID]) -> list[StudentRecord]:
        """Return the active students of the groups."""
        if not group_ids:
            return []
        stmt = _select().where(
            Student.group_id.in_(list(group_ids)), Student.status == "active"
        )
        return [_record(row) for row in (await self.session.execute(stmt)).all()]

    async def by_ids(self, user_ids: Sequence[UUID]) -> list[StudentRecord]:
        """Return the students with these ids, whatever their status."""
        if not user_ids:
            return []
        stmt = _select().where(Student.user_id.in_(list(user_ids)))
        return [_record(row) for row in (await self.session.execute(stmt)).all()]
