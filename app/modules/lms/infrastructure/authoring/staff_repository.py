"""SQLAlchemy repository of course staff."""

from uuid import UUID

from app.modules.lms.domain.authoring.entities import StaffMember
from app.modules.lms.infrastructure.orm import CourseStaff as StaffRow

from sqlalchemy import any_, delete, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlStaffRepository:
    """Reads and writes `lms.course_staff`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def list_for_course(self, course_id: UUID) -> list[StaffMember]:
        """Return the staff ordered by position."""
        statement = (
            select(StaffRow)
            .where(StaffRow.course_id == course_id)
            .order_by(StaffRow.position, StaffRow.created_at, StaffRow.id)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]

    async def get(self, course_id: UUID, user_id: UUID) -> StaffMember | None:
        """Return one staff member, or None."""
        row = await self._row(course_id, user_id)
        return None if row is None else _to_entity(row)

    async def add(self, member: StaffMember) -> None:
        """Insert a staff member."""
        row = StaffRow()
        _apply(row, member)
        self.session.add(row)
        await self.session.flush()

    async def save(self, member: StaffMember) -> None:
        """Write role, permissions, visibility and position."""
        row = await self._row(member.course_id, member.user_id)
        if row is not None:
            _apply(row, member)
            await self.session.flush()

    async def remove(self, course_id: UUID, user_id: UUID) -> None:
        """Delete a staff member."""
        await self.session.execute(
            delete(StaffRow)
            .where(StaffRow.course_id == course_id, StaffRow.user_id == user_id)
            .execution_options(synchronize_session=False)
        )

    async def count_with_permission(self, course_id: UUID, permission: str) -> int:
        """Count staff members holding the permission."""
        count = await self.session.scalar(
            select(func.count())
            .select_from(StaffRow)
            .where(
                StaffRow.course_id == course_id,
                literal(permission) == any_(StaffRow.permissions),
            )
        )
        return int(count or 0)

    async def _row(self, course_id: UUID, user_id: UUID) -> StaffRow | None:
        statement = (
            select(StaffRow)
            .where(StaffRow.course_id == course_id, StaffRow.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.scalars(statement)).one_or_none()


def _to_entity(row: StaffRow) -> StaffMember:
    return StaffMember(
        course_id=row.course_id,
        user_id=row.user_id,
        role=row.role,
        permissions=list(row.permissions),
        show_on_page=row.show_on_page,
        position=row.position,
        added_by=row.added_by,
    )


def _apply(row: StaffRow, member: StaffMember) -> None:
    row.course_id = member.course_id
    row.user_id = member.user_id
    row.role = member.role
    row.permissions = list(member.permissions)
    row.show_on_page = member.show_on_page
    row.position = member.position
    row.added_by = member.added_by
