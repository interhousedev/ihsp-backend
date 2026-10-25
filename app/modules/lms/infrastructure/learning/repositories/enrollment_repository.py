"""SQLAlchemy repository of enrollments."""

from uuid import UUID

from app.modules.lms.domain.learning.entities import Enrollment
from app.modules.lms.infrastructure.orm.enrollment import Enrollment as EnrollmentRow
from app.shared.ids import new_id

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: EnrollmentRow) -> Enrollment:
    """Map the ORM row to the entity."""
    return Enrollment(
        id=row.id,
        course_id=row.course_id,
        user_id=row.user_id,
        via=row.via,
        completed_at=row.completed_at,
        progress_pct=row.progress_pct,
        progress_version_id=row.progress_version_id,
        last_seen_version_id=row.last_seen_version_id,
    )


class SqlEnrollmentRepository:
    """Enrollments of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, course_id: UUID, user_id: UUID) -> Enrollment | None:
        """Return the enrollment of a user in a course."""
        row = await self.session.scalar(
            select(EnrollmentRow)
            .where(
                EnrollmentRow.course_id == course_id, EnrollmentRow.user_id == user_id
            )
            .execution_options(populate_existing=True)
        )
        return _to_entity(row) if row else None

    async def add(self, *, course_id: UUID, user_id: UUID, via: str) -> Enrollment:
        """Enroll the user; a repeated call returns the existing enrollment."""
        await self.session.execute(
            insert(EnrollmentRow)
            .values(id=new_id(), course_id=course_id, user_id=user_id, via=via)
            .on_conflict_do_nothing(index_elements=["course_id", "user_id"])
        )
        row = await self.session.scalar(
            select(EnrollmentRow)
            .where(
                EnrollmentRow.course_id == course_id, EnrollmentRow.user_id == user_id
            )
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - the insert above guarantees the row
            raise LookupError("enrollment vanished")
        return _to_entity(row)

    async def save(self, enrollment: Enrollment) -> None:
        """Store progress, completion and the last seen version."""
        await self.session.execute(
            update(EnrollmentRow)
            .where(EnrollmentRow.id == enrollment.id)
            .values(
                completed_at=enrollment.completed_at,
                progress_pct=enrollment.progress_pct,
                progress_version_id=enrollment.progress_version_id,
                last_seen_version_id=enrollment.last_seen_version_id,
            )
        )

    async def list_for_user(self, user_id: UUID) -> list[Enrollment]:
        """Return all enrollments of a user."""
        rows = await self.session.scalars(
            select(EnrollmentRow)
            .where(EnrollmentRow.user_id == user_id)
            .order_by(EnrollmentRow.created_at)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]

    async def list_for_course(self, course_id: UUID) -> list[Enrollment]:
        """Return all enrollments in a course."""
        rows = await self.session.scalars(
            select(EnrollmentRow)
            .where(EnrollmentRow.course_id == course_id)
            .order_by(EnrollmentRow.created_at)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]
