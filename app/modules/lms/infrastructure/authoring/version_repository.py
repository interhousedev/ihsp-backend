"""SQLAlchemy repository of course versions."""

from uuid import UUID

from app.modules.lms.domain.authoring.entities import CourseVersion
from app.modules.lms.infrastructure.orm import CourseVersion as VersionRow

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlVersionRepository:
    """Reads and appends `lms.course_versions`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, version: CourseVersion) -> None:
        """Insert a version."""
        row = VersionRow()
        row.id = version.id
        row.course_id = version.course_id
        row.number = version.number
        row.meta = version.meta
        row.outline = version.outline
        row.changes = version.changes
        row.note = version.note
        row.published_by = version.published_by
        row.created_at = version.created_at
        row.updated_at = version.created_at
        self.session.add(row)
        await self.session.flush()

    async def next_number(self, course_id: UUID) -> int:
        """Return the number the next version gets (call under the course lock)."""
        highest = await self.session.scalar(
            select(func.coalesce(func.max(VersionRow.number), 0)).where(
                VersionRow.course_id == course_id
            )
        )
        return int(highest or 0) + 1

    async def get(self, version_id: UUID) -> CourseVersion | None:
        """Return a version by ID, or None."""
        statement = (
            select(VersionRow)
            .where(VersionRow.id == version_id)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.scalars(statement)).one_or_none()
        return None if row is None else _to_entity(row)

    async def get_by_number(self, course_id: UUID, number: int) -> CourseVersion | None:
        """Return a version by its number, or None."""
        statement = (
            select(VersionRow)
            .where(VersionRow.course_id == course_id, VersionRow.number == number)
            .execution_options(populate_existing=True)
        )
        row = (await self.session.scalars(statement)).one_or_none()
        return None if row is None else _to_entity(row)

    async def list_for_course(self, course_id: UUID) -> list[CourseVersion]:
        """Return the versions, newest first."""
        statement = (
            select(VersionRow)
            .where(VersionRow.course_id == course_id)
            .order_by(VersionRow.number.desc())
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]


def _to_entity(row: VersionRow) -> CourseVersion:
    return CourseVersion(
        id=row.id,
        course_id=row.course_id,
        number=row.number,
        meta=row.meta,
        outline=row.outline,
        changes=row.changes,
        published_by=row.published_by,
        created_at=row.created_at,
        note=row.note,
    )
