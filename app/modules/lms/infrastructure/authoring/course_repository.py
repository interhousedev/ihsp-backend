"""SQLAlchemy repository of courses."""

from datetime import datetime
from uuid import UUID

from app.modules.lms.domain.authoring.course_settings import derive_publish_state
from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import (
    CourseNotFoundError,
    SlugTakenError,
)
from app.modules.lms.infrastructure.orm import Course as CourseRow
from app.modules.lms.infrastructure.orm import CourseStaff as StaffRow
from app.modules.lms.infrastructure.orm import Enrollment as EnrollmentRow

from sqlalchemy import any_, func, literal, select, update
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

    async def count_learners(self, course_id: UUID) -> int:
        """Return the number of enrollments of the course."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(EnrollmentRow)
            .where(EnrollmentRow.course_id == course_id)
        )
        return int(total or 0)

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
        code=row.code,
        friendly_name=row.friendly_name,
        summary=row.summary,
        banner_file_id=row.banner_file_id,
        accent_color=row.accent_color,
        language=row.language,
        level=row.level,
        workload_hours_per_week=row.workload_hours_per_week,
        duration_weeks=row.duration_weeks,
        tags=list(row.tags or []),
        outcomes=list(row.outcomes or []),
        requirements=list(row.requirements or []),
        audience=list(row.audience or []),
        audience_scope=row.audience_scope,
        audience_group_ids=list(row.audience_group_ids or []),
        enrolment_open=row.enrolment_open,
        enrolment_starts_at=row.enrolment_starts_at,
        enrolment_ends_at=row.enrolment_ends_at,
        navigation=list(row.navigation or []),
        publish_state=row.publish_state,
        link_report=row.link_report,
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
    row.code = course.code
    row.friendly_name = course.friendly_name
    row.summary = course.summary
    row.banner_file_id = course.banner_file_id
    row.accent_color = course.accent_color
    row.language = course.language
    row.level = course.level
    row.workload_hours_per_week = course.workload_hours_per_week
    row.duration_weeks = course.duration_weeks
    row.tags = course.tags
    row.outcomes = course.outcomes
    row.requirements = course.requirements
    row.audience = course.audience
    row.audience_scope = course.audience_scope
    row.audience_group_ids = course.audience_group_ids
    row.enrolment_open = course.enrolment_open
    row.enrolment_starts_at = course.enrolment_starts_at
    row.enrolment_ends_at = course.enrolment_ends_at
    row.navigation = course.navigation
    # Derived, so it can never disagree with `status` and `live_version_id`.
    row.publish_state = derive_publish_state(course)
    row.link_report = course.link_report
