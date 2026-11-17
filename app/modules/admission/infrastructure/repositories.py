"""SQL repositories of the admission foundation."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.access import (
    Assignment,
    Entitlement,
    EntitlementKind,
    GrantedVia,
    ScopeKind,
    StaffRole,
)
from app.modules.admission.domain.courses import Course, CourseSource
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.questions import QUESTION_SET_VERSION
from app.modules.admission.infrastructure.orm.access import (
    AuditEventRow,
    EntitlementRow,
    RuntimeSettingRow,
    StaffAssignmentRow,
    StaffRoleRow,
)
from app.modules.admission.infrastructure.orm.profile import CourseRow, ProfileRow
from app.modules.admission.ports.repositories import AuditEvent, OptIns
from app.shared.ids import new_id

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _role(row: StaffRoleRow) -> StaffRole:
    known = {p.value for p in Permission}
    return StaffRole(
        id=row.id,
        kind=row.kind,
        name=row.name,
        name_i18n=dict(row.name_i18n or {}),
        permissions=frozenset(Permission(p) for p in row.permissions if p in known),
        is_builtin=row.is_builtin,
        archived_at=row.archived_at,
        lock_version=row.lock_version,
    )


def _course(row: CourseRow) -> Course:
    return Course(
        student_id=row.student_id,
        source=cast(CourseSource, row.source),
        source_ref=row.source_ref,
        title=row.title,
        provider=row.provider,
        level=row.level,
        year=row.year,
        grade=row.grade,
        included=row.included,
        id=row.id,
        created_at=row.created_at,
    )


class SqlAccessRepository:
    """Entitlements, assignments, help grants and audit events."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def entitlement(self, user_id: UUID) -> Entitlement | None:
        """Return the stored entitlement row."""
        row = await self._s.get(EntitlementRow, user_id)
        if row is None:
            return None
        return Entitlement(
            user_id=row.user_id,
            kind=cast(EntitlementKind, row.kind),
            cohort_year=row.cohort_year,
            granted_by=row.granted_by,
            granted_at=row.granted_at,
            revoked_at=row.revoked_at,
            lock_version=row.lock_version,
        )

    async def assignments_for(self, user_id: UUID) -> tuple[Assignment, ...]:
        """Return the unrevoked assignments with their roles."""
        rows = await self._s.execute(
            select(StaffAssignmentRow, StaffRoleRow)
            .join(StaffRoleRow, StaffRoleRow.id == StaffAssignmentRow.staff_role_id)
            .where(
                StaffAssignmentRow.user_id == user_id,
                StaffAssignmentRow.revoked_at.is_(None),
            )
            .order_by(StaffAssignmentRow.starts_at)
        )
        return tuple(
            Assignment(
                id=a.id,
                user_id=a.user_id,
                role=_role(r),
                scope_kind=cast(ScopeKind, a.scope_kind),
                scope_ref=a.scope_ref,
                starts_at=a.starts_at,
                expires_at=a.expires_at,
                granted_by=a.granted_by,
                granted_via=cast(GrantedVia, a.granted_via),
                parent_assignment_id=a.parent_assignment_id,
                revoked_at=a.revoked_at,
            )
            for a, r in rows.tuples()
        )


    async def opt_ins(self, user_ids: Sequence[UUID]) -> dict[UUID, OptIns]:
        """Return the mentoring switches of existing profiles."""
        if not user_ids:
            return {}
        rows = await self._s.execute(
            select(
                ProfileRow.student_id,
                ProfileRow.mentee_opt_in,
                ProfileRow.mentor_opt_in,
            ).where(ProfileRow.student_id.in_(list(user_ids)))
        )
        return {sid: OptIns(mentee, mentor) for sid, mentee, mentor in rows.tuples()}

    async def set_opt_in(self, user_id: UUID, field: str, value: bool) -> None:
        """Upsert one mentoring switch of the user's profile row."""
        if field not in ("mentee_opt_in", "mentor_opt_in"):
            raise ValueError(field)
        stmt = pg_insert(ProfileRow).values(
            student_id=user_id,
            question_set_version=QUESTION_SET_VERSION,
            **{field: value},
        )
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["student_id"], set_={field: value}
            )
        )

    def audit(self, event: AuditEvent) -> None:
        """Add the audit row to the session."""
        self._s.add(
            AuditEventRow(
                id=new_id(),
                actor_id=event.actor_id,
                actor_kind=event.actor_kind,
                action=event.action,
                student_id=event.student_id,
                object_type=event.object_type,
                object_id=event.object_id,
                staff_role_id=event.staff_role_id,
                meta=event.meta,
            )
        )


class SqlCourseRepository:
    """Stored course rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[Course]:
        """Return the student's rows, oldest first."""
        rows = await self._s.scalars(
            select(CourseRow)
            .where(CourseRow.student_id == student_id)
            .order_by(CourseRow.created_at, CourseRow.id)
        )
        return [_course(r) for r in rows]

    async def get(self, course_id: UUID) -> Course | None:
        """Return one row."""
        row = await self._s.get(CourseRow, course_id)
        return _course(row) if row else None

    async def find(
        self, student_id: UUID, source: str, source_ref: str
    ) -> Course | None:
        """Return the stored row of a source course."""
        row = await self._s.scalar(
            select(CourseRow).where(
                CourseRow.student_id == student_id,
                CourseRow.source == source,
                CourseRow.source_ref == source_ref,
            )
        )
        return _course(row) if row else None

    async def add(self, course: Course) -> Course:
        """Insert the row."""
        row = CourseRow(
            id=new_id(),
            student_id=course.student_id,
            source=course.source,
            source_ref=course.source_ref,
            title=course.title,
            provider=course.provider,
            level=course.level,
            year=course.year,
            grade=course.grade,
            included=course.included,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _course(row)

    async def set_included(self, course_id: UUID, included: bool) -> Course:
        """Change the flag."""
        row = await self._s.get(CourseRow, course_id, with_for_update=True)
        if row is None:
            raise AdmissionNotFoundError()
        row.included = included
        await self._s.flush()
        return _course(row)


class SqlRuntimeSettingsRepository:
    """Admin-edited settings."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def load(self) -> dict[str, Any]:
        """Return all stored values."""
        rows = await self._s.execute(
            select(RuntimeSettingRow.key, RuntimeSettingRow.value)
        )
        return dict(rows.tuples().all())

    async def save(self, key: str, value: Any, user_id: UUID) -> None:
        """Upsert one value."""
        stmt = pg_insert(RuntimeSettingRow).values(
            key=key, value=value, updated_by=user_id
        )
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"value": stmt.excluded.value, "updated_by": user_id},
            )
        )
