"""Staff caseload, delegated assignments and saved views."""

import datetime as dt
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    SavedViewLimitError,
)
from app.modules.admission.domain.permissions import KIND_ROLE, Permission
from app.modules.admission.domain.staff import (
    MAX_SAVED_VIEWS,
    MAX_VIEW_NAME,
    VIEW_FILTER_KEYS,
    CaseloadRow,
    SavedView,
    deny,
    pick_parent,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.staff import StaffDirectory
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.academic import AcademicMembership
from app.shared.contracts.identity import IdentityDirectory, UserRef, UserStatus
from app.shared.ids import new_id

ASSIGNABLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class CaseloadFilters:
    """Filters of the caseload list."""

    stage: str | None = None
    risk: bool = False
    deadline_before: dt.datetime | None = None
    group_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CaseloadItem:
    """A caseload row with the student's class."""

    row: CaseloadRow
    group_id: UUID | None
    limited: bool
    student_name: str | None = None


def _clean_view(name: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = name.strip()
    if not name or len(name) > MAX_VIEW_NAME:
        raise ValidationFailedError(params={"field": "name"})
    unknown = set(filters) - VIEW_FILTER_KEYS
    if unknown:
        raise ValidationFailedError(params={"field": sorted(unknown)[0]})
    return name, dict(filters)


def display_name(user: UserRef) -> str:
    """Return "Last First" of a user."""
    return f"{user.last_name} {user.first_name}".strip()


def _passes(filters: CaseloadFilters, row: CaseloadRow, student: Any) -> bool:
    """Whether a caseload row survives the filters."""
    if filters.group_id and (not student or student.group_id != filters.group_id):
        return False
    if filters.stage and row.stage != filters.stage:
        return False
    if filters.risk and row.overdue == 0:
        return False
    due = filters.deadline_before
    return not (due and (row.next_due is None or row.next_due > due))


class StaffService:
    """The staff member's list of students, delegation and saved views."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        membership: AcademicMembership,
        directory: StaffDirectory | None,
        clock: Clock,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._membership = membership
        self._directory = directory
        self._clock = clock
        self._identity = identity

    @staticmethod
    def _empty_caseload(ctx: AdmissionContext) -> list[CaseloadItem]:
        """An admin without assignments reaches no student; others are refused."""
        if Role.ADMIN in ctx.actor.roles:
            return []
        raise AdmissionForbiddenError(params={"permission": "caseload"})

    async def caseload(
        self, ctx: AdmissionContext, filters: CaseloadFilters
    ) -> list[CaseloadItem]:
        """List the students the caller reaches, filtered, soonest deadline first."""
        scope = self._access.scope(ctx)
        if scope.empty:
            return self._empty_caseload(ctx)
        ids = await self._access.students_in_scope(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            rows = await uow.staff.caseload(ids, now)
        names = await self._names([r.student_id for r in rows])
        items: list[CaseloadItem] = []
        for row in rows:
            if row.student_id == ctx.user_id:
                continue
            resolution = await self._access.resolve(ctx, row.student_id)
            if not resolution.in_scope:
                continue
            student = await self._membership.student(row.student_id)
            if not _passes(filters, row, student):
                continue
            if resolution.limited:
                row = replace(row, stage=None, open_help=0)
            if student:
                row = replace(row, group_name=student.group_name)
            group_id = student.group_id if student else None
            ref = names.get(row.student_id)
            items.append(
                CaseloadItem(
                    row,
                    group_id,
                    resolution.limited,
                    display_name(ref) if ref else None,
                )
            )
        return items

    async def _names(self, ids: list[UUID]) -> dict[UUID, UserRef]:
        if self._identity is None or not ids:
            return {}
        return await self._identity.get_users(ids)

    async def assign(
        self,
        ctx: AdmissionContext,
        *,
        user_id: UUID,
        staff_role_id: UUID,
        scope_kind: str,
        scope_ref: UUID | None,
        expires_at: dt.datetime | None,
    ) -> Assignment:
        """Delegate a sub-role (§4.5); raises DelegationDeniedError with a reason."""
        now = self._clock.now()
        if scope_kind not in ("student", "cohort"):
            raise deny("scope")
        student_id = scope_ref if scope_kind == "student" else None
        groups: frozenset[UUID] = frozenset()
        if student_id is not None:
            await self._access.require(
                ctx,
                student_id,
                Permission.STUDENTS_ASSIGN,
                object_type="assignment",
            )
            groups = (await self._membership.group_ids_for([student_id])).get(
                student_id, frozenset()
            )
        if expires_at is not None and expires_at <= now:
            raise deny("expiry")
        target = await self._directory.staff_user(user_id) if self._directory else None
        async with self._uow() as uow:
            role = await uow.staff.role(staff_role_id)
            if role is None or role.archived_at is not None:
                raise AdmissionNotFoundError()
            grantors = [
                a
                for a in ctx.assignments
                if Permission.STUDENTS_ASSIGN in a.role.effective_permissions
                and KIND_ROLE.get(a.role.kind) in ctx.actor.roles
            ]
            parent = pick_parent(
                ctx.user_id,
                grantors,
                target,
                role,
                scope_kind,
                scope_ref,
                expires_at,
                groups,
                student_id,
                now,
            )
            if role.kind == "mentor":
                if student_id is None:
                    raise deny("scope")
                opt = await uow.access.opt_ins([user_id, student_id])
                mine, theirs = opt.get(user_id), opt.get(student_id)
                agreed = mine and mine.mentor_opt_in and theirs and theirs.mentee_opt_in
                if not agreed:
                    raise deny("opt_in")
            created = await uow.staff.add_assignment(
                Assignment(
                    id=new_id(),
                    user_id=user_id,
                    role=role,
                    scope_kind=scope_kind,  # type: ignore[arg-type]
                    scope_ref=scope_ref,
                    starts_at=now,
                    expires_at=expires_at,
                    granted_by=ctx.user_id,
                    granted_via="delegation",
                    parent_assignment_id=parent.id,
                )
            )
            await uow.commit()
        return created

    async def assignable_roles(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[StaffRole]:
        """Sub-roles the caller may pick for a student they may assign for."""
        await self._require_assign(ctx, student_id)
        async with self._uow() as uow:
            return [r for r in await uow.staff.roles() if r.kind in KIND_ROLE]

    async def assignable_users(
        self, ctx: AdmissionContext, student_id: UUID, query: str
    ) -> list[UserRef]:
        """Active admission staff (counselors, mentors, officers) matching a name."""
        await self._require_assign(ctx, student_id)
        if self._identity is None:
            return []
        users = await self._identity.search_users(
            query.strip(), roles=tuple(KIND_ROLE.values()), limit=ASSIGNABLE_LIMIT
        )
        return [
            u
            for u in users
            if u.status == UserStatus.ACTIVE and u.id not in (student_id, ctx.user_id)
        ]

    async def _require_assign(self, ctx: AdmissionContext, student_id: UUID) -> None:
        await self._access.require(
            ctx,
            student_id,
            Permission.STUDENTS_ASSIGN,
            object_type="assignment",
        )

    async def revoke(self, ctx: AdmissionContext, assignment_id: UUID) -> None:
        """Revoke an assignment the caller delegated (or its parent holder's)."""
        now = self._clock.now()
        async with self._uow() as uow:
            row = await uow.staff.assignment(assignment_id)
            live = {a.id for a in ctx.assignments if a.active_at(now)}
            if (
                row is None
                or row.revoked_at is not None
                or (
                    row.granted_by != ctx.user_id
                    and row.parent_assignment_id not in live
                )
            ):
                raise AdmissionNotFoundError()
            await uow.staff.revoke_assignment(assignment_id, now, "revoked")
            await uow.commit()

    async def views(self, ctx: AdmissionContext) -> list[SavedView]:
        """Return the caller's saved views."""
        async with self._uow() as uow:
            return await uow.staff.saved_views(ctx.user_id)

    async def add_view(
        self,
        ctx: AdmissionContext,
        name: str,
        filters: dict[str, Any],
        sort: str | None,
        is_default: bool,
    ) -> SavedView:
        """Save a view; at most MAX_SAVED_VIEWS per user."""
        name, filters = _clean_view(name, filters)
        async with self._uow() as uow:
            if len(await uow.staff.saved_views(ctx.user_id)) >= MAX_SAVED_VIEWS:
                raise SavedViewLimitError()
            view = await uow.staff.add_saved_view(
                SavedView(new_id(), ctx.user_id, name, filters, sort, is_default)
            )
            await uow.commit()
        return view

    async def update_view(
        self,
        ctx: AdmissionContext,
        view_id: UUID,
        *,
        name: str,
        filters: dict[str, Any],
        sort: str | None,
        is_default: bool,
        lock_version: int,
    ) -> SavedView:
        """Replace a view of the caller; a stale lock_version is a conflict."""
        name, filters = _clean_view(name, filters)
        async with self._uow() as uow:
            mine = {v.id for v in await uow.staff.saved_views(ctx.user_id)}
            if view_id not in mine:
                raise AdmissionNotFoundError()
            view = await uow.staff.update_saved_view(
                SavedView(
                    view_id, ctx.user_id, name, filters, sort, is_default, lock_version
                )
            )
            await uow.commit()
        return view

    async def delete_view(self, ctx: AdmissionContext, view_id: UUID) -> None:
        """Delete a view of the caller."""
        async with self._uow() as uow:
            if not await uow.staff.delete_saved_view(view_id, ctx.user_id):
                raise AdmissionNotFoundError()
            await uow.commit()

    # -- officers covering all students (admin only) ---------------------

    @staticmethod
    def _need_admin(ctx: AdmissionContext) -> None:
        if Role.ADMIN not in ctx.actor.roles:
            raise AdmissionForbiddenError(params={"permission": "officers:cover_all"})

    async def covering_officers(
        self, ctx: AdmissionContext
    ) -> list[tuple[Assignment, UserRef | None]]:
        """Transcript officers who cover every student right now (admin)."""
        self._need_admin(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            rows = await uow.staff.live_assignments("transcript_officer", "all")
        rows = [a for a in rows if a.active_at(now)]
        names = await self._names([a.user_id for a in rows])
        return [(a, names.get(a.user_id)) for a in rows]

    async def officer_candidates(
        self, ctx: AdmissionContext, query: str
    ) -> list[UserRef]:
        """Active transcript officers matching a name (admin)."""
        self._need_admin(ctx)
        if self._identity is None:
            return []
        users = await self._identity.search_users(
            query.strip(), roles=(Role.TRANSCRIPT_OFFICER,), limit=ASSIGNABLE_LIMIT
        )
        return [u for u in users if u.status == UserStatus.ACTIVE]

    async def cover_all(
        self, ctx: AdmissionContext, user_id: UUID, expires_at: dt.datetime | None
    ) -> Assignment:
        """Make an officer cover every student's transcript requests (admin only)."""
        self._need_admin(ctx)
        now = self._clock.now()
        if expires_at is not None and expires_at <= now:
            raise deny("expiry")
        target = await self._directory.staff_user(user_id) if self._directory else None
        if target is None:
            raise deny("target")
        if not target.active:
            raise deny("inactive")
        if Role.TRANSCRIPT_OFFICER.value not in target.roles:
            raise deny("global_role")
        async with self._uow() as uow:
            roles = [
                r
                for r in await uow.staff.roles()
                if r.kind == "transcript_officer" and r.archived_at is None
            ]
            if not roles:
                raise AdmissionNotFoundError()
            role = max(roles, key=lambda r: r.is_builtin)
            created = await uow.staff.add_assignment(
                Assignment(
                    id=new_id(),
                    user_id=user_id,
                    role=role,
                    scope_kind="all",
                    scope_ref=None,
                    starts_at=now,
                    expires_at=expires_at,
                    granted_by=ctx.user_id,
                    granted_via="admin",
                )
            )
            uow.access.audit(
                AuditEvent(
                    "officer.covers_all_granted",
                    ctx.user_id,
                    None,
                    object_type="assignment",
                    object_id=created.id,
                    staff_role_id=role.id,
                    meta={"user_id": str(user_id)},
                )
            )
            await uow.commit()
        return created

    async def uncover_all(self, ctx: AdmissionContext, assignment_id: UUID) -> None:
        """Take the all-students coverage away from an officer (admin only)."""
        self._need_admin(ctx)
        now = self._clock.now()
        async with self._uow() as uow:
            row = await uow.staff.assignment(assignment_id)
            if (
                row is None
                or row.revoked_at is not None
                or row.scope_kind != "all"
                or row.role.kind != "transcript_officer"
            ):
                raise AdmissionNotFoundError()
            await uow.staff.revoke_assignment(assignment_id, now, "revoked")
            uow.access.audit(
                AuditEvent(
                    "officer.covers_all_revoked",
                    ctx.user_id,
                    None,
                    object_type="assignment",
                    object_id=assignment_id,
                    staff_role_id=row.role.id,
                    meta={"user_id": str(row.user_id)},
                )
            )
            await uow.commit()


__all__ = ["CaseloadFilters", "CaseloadItem", "StaffService"]
