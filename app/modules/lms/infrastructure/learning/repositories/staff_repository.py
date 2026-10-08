"""SQLAlchemy repository of course staff (read only)."""

from uuid import UUID

from app.modules.lms.domain.learning.entities import StaffMember
from app.modules.lms.infrastructure.orm.course_staff import CourseStaff

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: CourseStaff) -> StaffMember:
    """Map the ORM row to a staff member."""
    return StaffMember(
        user_id=row.user_id,
        role=row.role,
        permissions=frozenset(row.permissions),
        show_on_page=row.show_on_page,
        position=row.position,
    )


class SqlStaffRepository:
    """Course staff of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, course_id: UUID, user_id: UUID) -> StaffMember | None:
        """Return the staff row of a user in a course."""
        row = await self.session.scalar(
            select(CourseStaff).where(
                CourseStaff.course_id == course_id, CourseStaff.user_id == user_id
            )
        )
        return _to_entity(row) if row else None

    async def list_on_page(self, course_id: UUID) -> list[StaffMember]:
        """Return staff shown on the course page, ordered by position."""
        rows = await self.session.scalars(
            select(CourseStaff)
            .where(CourseStaff.course_id == course_id, CourseStaff.show_on_page)
            .order_by(CourseStaff.position, CourseStaff.created_at, CourseStaff.id)
        )
        return [_to_entity(row) for row in rows]

    async def course_ids_of(self, user_id: UUID) -> list[UUID]:
        """Return the courses where the user is on the staff."""
        rows = await self.session.scalars(
            select(CourseStaff.course_id).where(CourseStaff.user_id == user_id)
        )
        return list(rows)
