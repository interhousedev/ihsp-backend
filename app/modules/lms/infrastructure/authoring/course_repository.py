"""SQLAlchemy repository of courses."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import (
    CourseNotFoundError,
    SlugTakenError,
)
from app.modules.lms.infrastructure.orm import Course as CourseRow
from app.modules.lms.infrastructure.orm import CourseStaff as StaffRow

from sqlalchemy import any_, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class SqlCourseRepository:
    """Reads and writes `lms.courses`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def get(self, course_id: UUID) -> Course | None:
        """Return the course, or None."""
        row = await self._row(course_id)
        return None if row is None else _to_entity(row)

    async def get_locked(self, course_id: UUID) -> Course | None:
        """Return the course and lock its row until the transaction ends."""
        row = await self._row(course_id, lock=True)
        return None if row is None else _to_entity(row)

    async def add(self, course: Course) -> None:
        """Insert a course; raise SlugTakenError if the slug is used."""
        row = CourseRow()
        _apply(row, course)
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise SlugTakenError(params={"slug": course.slug}) from exc

    async def save(self, course: Course) -> None:
        """Write every mutable field (call only while holding the row lock)."""
        row = await self._row(course.id)
        if row is None:
            raise CourseNotFoundError(params={"course_id": str(course.id)})
        _apply(row, course)
        await self.session.flush()

    async def slug_exists(self, slug: str) -> bool:
        """Return True if a course already uses the slug."""
        found = await self.session.scalar(
            select(CourseRow.id).where(CourseRow.slug == slug)
        )
        return found is not None

    async def touch_draft(self, course_id: UUID, *, by: UUID, now: datetime) -> int:
        """Atomically bump `draft_seq`, which also takes the row lock; return it."""
        statement = (
            update(CourseRow)
            .where(CourseRow.id == course_id)
            .values(
                draft_seq=CourseRow.draft_seq + 1,
                draft_updated_by=by,
                draft_updated_at=now,
            )
            .returning(CourseRow.draft_seq)
            .execution_options(synchronize_session=False)
        )
        seq = (await self.session.execute(statement)).scalar_one_or_none()
        if seq is None:
            raise CourseNotFoundError(params={"course_id": str(course_id)})
        return int(seq)

    async def list_all(self) -> list[Course]:
        """Return every course, newest first (for LMS admins)."""
        statement = (
            select(CourseRow)
            .order_by(CourseRow.created_at.desc(), CourseRow.id.desc())
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]

    async def list_for_user(self, user_id: UUID, permission: str) -> list[Course]:
        """Return courses where the user holds the permission."""
        statement = (
            select(CourseRow)
            .join(StaffRow, StaffRow.course_id == CourseRow.id)
            .where(
                StaffRow.user_id == user_id,
                literal(permission) == any_(StaffRow.permissions),
            )
            .order_by(CourseRow.created_at.desc(), CourseRow.id.desc())
            .execution_options(populate_existing=True)
        )
        return [_to_entity(r) for r in (await self.session.scalars(statement))]

    async def _row(self, course_id: UUID, *, lock: bool = False) -> CourseRow | None:
        statement = (
            select(CourseRow)
            .where(CourseRow.id == course_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()


def _to_entity(row: CourseRow) -> Course:
    return Course(
        id=row.id,
        slug=row.slug,
        title=row.title,
        description=row.description,
        visibility=Visibility(row.visibility),
        status=CourseStatus(row.status),
        created_by=row.created_by,
        draft_meta=row.draft_meta,
        draft_outline=row.draft_outline,
        outline_hash=row.outline_hash,
        cover_file_id=row.cover_file_id,
        invite_code=row.invite_code,
        draft_updated_by=row.draft_updated_by,
        draft_updated_at=row.draft_updated_at,
        lock_version=row.lock_version,
        draft_seq=row.draft_seq,
        live_outline_hash=row.live_outline_hash,
        live_version_id=row.live_version_id,
    )


def _apply(row: CourseRow, course: Course) -> None:
    row.id = course.id
    row.slug = course.slug
    row.title = course.title
    row.description = course.description
    row.cover_file_id = course.cover_file_id
    row.visibility = course.visibility.value
    row.invite_code = course.invite_code
    row.status = course.status.value
    row.created_by = course.created_by
    row.draft_meta = course.draft_meta
    row.draft_outline = course.draft_outline
    row.draft_updated_by = course.draft_updated_by
    row.draft_updated_at = course.draft_updated_at
    row.lock_version = course.lock_version
    row.draft_seq = course.draft_seq
    row.outline_hash = course.outline_hash
    row.live_outline_hash = course.live_outline_hash
    row.live_version_id = course.live_version_id
