"""SQL repository of academic student rows."""

from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.infrastructure.orm import Student as StudentRow
from app.modules.academic.infrastructure.schedule.mappers import (
    student_apply,
    student_new_row,
    student_to_entity,
)

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def audience_condition(keys: Sequence[str]) -> ColumnElement[bool]:
    """Match students who attend a lesson with these keys.

    A group key matches the whole group; a subgroup key also matches students
    whose subgroup is not set yet.
    """
    clauses: list[ColumnElement[bool]] = []
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        if subgroup is None:
            clauses.append(StudentRow.group_id == group_id)
        else:
            clauses.append(
                and_(
                    StudentRow.group_id == group_id,
                    or_(StudentRow.subgroup.is_(None), StudentRow.subgroup == subgroup),
                )
            )
    return or_(*clauses)


class SqlStudentRepository:
    """Students in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, user_id: UUID) -> Student | None:
        """Return the student or None."""
        row = await self.session.get(StudentRow, user_id)
        return student_to_entity(row) if row else None

    async def get_many(self, user_ids: Collection[UUID]) -> dict[UUID, Student]:
        """Return the students that exist, by user id."""
        if not user_ids:
            return {}
        rows = await self.session.scalars(
            select(StudentRow).where(StudentRow.user_id.in_(list(user_ids)))
        )
        return {row.user_id: student_to_entity(row) for row in rows}

    async def add(self, student: Student) -> None:
        """Insert a student."""
        self.session.add(student_new_row(student))
        await self.session.flush()

    async def save(self, student: Student) -> None:
        """Write the changes of a student."""
        row = await self.session.get(StudentRow, student.user_id)
        if row is None:
            return
        student_apply(row, student)
        await self.session.flush()

    async def list_filtered(
        self,
        *,
        group_id: UUID | None = None,
        subgroup: int | None = None,
        status: str | None = None,
    ) -> list[Student]:
        """Return students matching the filters (all when none are given)."""
        stmt = select(StudentRow)
        if group_id is not None:
            stmt = stmt.where(StudentRow.group_id == group_id)
        if subgroup is not None:
            stmt = stmt.where(StudentRow.subgroup == subgroup)
        if status is not None:
            stmt = stmt.where(StudentRow.status == status)
        rows = await self.session.scalars(stmt)
        return [student_to_entity(row) for row in rows]

    async def user_ids_for_audience(self, keys: Sequence[str]) -> list[UUID]:
        """Return active students who attend a lesson with these audience keys."""
        if not keys:
            return []
        stmt = select(StudentRow.user_id).where(
            StudentRow.status == "active", audience_condition(keys)
        )
        return list(await self.session.scalars(stmt))

    async def set_calendar_token_hash(self, user_id: UUID, token_hash: str) -> bool:
        """Store the hash of the student's iCal feed token; False if no such student."""
        result = await self.session.execute(
            update(StudentRow)
            .where(StudentRow.user_id == user_id)
            .values(calendar_token_hash=token_hash)
            .returning(StudentRow.user_id)
        )
        return result.first() is not None

    async def user_id_for_calendar_token(self, token_hash: str) -> UUID | None:
        """Return the active student whose iCal feed token has this hash."""
        stmt = select(StudentRow.user_id).where(
            StudentRow.calendar_token_hash == token_hash,
            StudentRow.status == "active",
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
