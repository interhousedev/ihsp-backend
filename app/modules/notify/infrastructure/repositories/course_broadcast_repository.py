"""SQL repository of course broadcasts (Core statements)."""

from uuid import UUID

from app.modules.notify.domain.course_broadcast import CourseBroadcast
from app.modules.notify.infrastructure.tables import course_broadcasts_table

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: RowMapping) -> CourseBroadcast:
    return CourseBroadcast(
        id=row["id"],
        course_id=row["course_id"],
        author_id=row["author_id"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
    )


class SqlCourseBroadcastRepository:
    """Reads and writes broadcast rows in the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session
        self.table = course_broadcasts_table()

    async def add(self, broadcast: CourseBroadcast) -> None:
        """Insert the broadcast."""
        await self.session.execute(
            sa.insert(self.table).values(
                id=broadcast.id,
                course_id=broadcast.course_id,
                author_id=broadcast.author_id,
                title=broadcast.title,
                body=broadcast.body,
                created_at=broadcast.created_at,
            )
        )

    async def list_for_course(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseBroadcast]:
        """Return the newest broadcasts of the course first."""
        rows = await self.session.execute(
            sa.select(self.table)
            .where(self.table.c.course_id == course_id)
            .order_by(self.table.c.created_at.desc(), self.table.c.id.desc())
            .limit(limit)
        )
        return [_to_entity(row) for row in rows.mappings()]
