"""SQLAlchemy repository of courses (learning side, read only)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.domain.learning.entities import LearningCourse
from app.modules.lms.infrastructure.orm.course import Course

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: Course) -> LearningCourse:
    """Map the ORM row to the learning entity (live values only)."""
    return LearningCourse(
        id=row.id,
        slug=row.slug,
        title=row.title,
        description=row.description,
        cover_file_id=row.cover_file_id,
        visibility=row.visibility,
        invite_code=row.invite_code,
        status=row.status,
        live_version_id=row.live_version_id,
        updated_at=row.updated_at,
    )


def _like_pattern(query: str) -> str:
    """Escape LIKE wildcards of user input."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqlCourseRepository:
    """Courses of the lms schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, course_id: UUID) -> LearningCourse | None:
        """Return the course by id."""
        row = await self.session.get(Course, course_id)
        return _to_entity(row) if row else None

    async def get_by_slug(self, slug: str) -> LearningCourse | None:
        """Return the course by its unique slug."""
        row = await self.session.scalar(select(Course).where(Course.slug == slug))
        return _to_entity(row) if row else None

    async def get_by_invite_code(self, code: str) -> LearningCourse | None:
        """Return the course that currently uses the invite code."""
        if not code:
            return None
        row = await self.session.scalar(
            select(Course).where(Course.invite_code == code)
        )
        return _to_entity(row) if row else None

    async def get_many(self, course_ids: Sequence[UUID]) -> list[LearningCourse]:
        """Return the courses with these ids, ordered by title."""
        if not course_ids:
            return []
        rows = await self.session.scalars(
            select(Course).where(Course.id.in_(course_ids)).order_by(Course.title)
        )
        return [_to_entity(row) for row in rows]

    async def search_published(
        self, query: str | None, *, limit: int
    ) -> list[LearningCourse]:
        """Return published, active, public courses whose title contains the query."""
        statement = select(Course).where(
            Course.live_version_id.is_not(None),
            Course.status == "active",
            Course.visibility == "public",
        )
        if query:
            statement = statement.where(
                Course.title.ilike(_like_pattern(query), escape="\\")
            )
        rows = await self.session.scalars(
            statement.order_by(Course.title, Course.id).limit(limit)
        )
        return [_to_entity(row) for row in rows]

    async def list_all(self, *, limit: int) -> list[LearningCourse]:
        """Return every course, ordered by title (for LMS administrators)."""
        rows = await self.session.scalars(
            select(Course).order_by(Course.title, Course.id).limit(limit)
        )
        return [_to_entity(row) for row in rows]
