"""SQLAlchemy repository of published course versions (read only)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.domain.learning.entities import LiveVersion
from app.modules.lms.domain.learning.live import parse_manifest
from app.modules.lms.infrastructure.orm.course_version import CourseVersion

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: CourseVersion) -> LiveVersion:
    """Map the ORM row to a version with a parsed manifest."""
    return LiveVersion(
        id=row.id,
        course_id=row.course_id,
        number=row.number,
        manifest=parse_manifest(row.outline),
        created_at=row.created_at,
    )


class SqlVersionRepository:
    """Course versions of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, version_id: UUID) -> LiveVersion | None:
        """Return a version by id."""
        row = await self.session.get(CourseVersion, version_id)
        return _to_entity(row) if row else None

    async def get_many(self, version_ids: Sequence[UUID]) -> dict[UUID, LiveVersion]:
        """Return the versions with these ids."""
        if not version_ids:
            return {}
        rows = await self.session.scalars(
            select(CourseVersion).where(CourseVersion.id.in_(set(version_ids)))
        )
        return {row.id: _to_entity(row) for row in rows}
