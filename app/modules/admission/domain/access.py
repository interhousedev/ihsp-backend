"""Entitlements, staff assignments and the pure permission resolver (§4)."""

import datetime as dt
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.permissions import (
    HELPER_SET,
    KIND_ALLOW_LIST,
    KIND_ROLE,
    NO_CONSENT_SET,
    NOT_DELEGABLE,
    OWNER_SET,
    Permission,
)
from app.shared.actor import Role

EntitlementKind = Literal["school_student", "alumni", "staff"]
ScopeKind = Literal["all", "cohort", "student"]
GrantedVia = Literal["admin", "delegation"]
IneligibleReason = Literal["not_in_grade", "no_entitlement", "blocked"]

APPLICANT_KINDS: Final = frozenset({"school_student", "alumni"})


@dataclass(frozen=True, slots=True)
class Entitlement:
    """Admission eligibility of a user, independent of the school student role."""

    user_id: UUID
    kind: EntitlementKind
    cohort_year: int | None
    granted_by: UUID | None
    granted_at: dt.datetime
    revoked_at: dt.datetime | None = None
    lock_version: int = 0

    @property
    def active(self) -> bool:
        """Return whether the entitlement is in force."""
        return self.revoked_at is None

    @property
    def is_applicant(self) -> bool:
        """Return whether the user may use the student side of the app."""
        return self.active and self.kind in APPLICANT_KINDS


@dataclass(frozen=True, slots=True)
class StaffRole:
    """A sub-role: a named permission set of one kind."""

    id: UUID
    kind: str
    name: str
    name_i18n: dict[str, str]
    permissions: frozenset[Permission]
    is_builtin: bool
    archived_at: dt.datetime | None = None
    lock_version: int = 0

    @property
    def effective_permissions(self) -> frozenset[Permission]:
        """Permissions clipped to the kind allow-list (enforced on every resolve)."""
        return self.permissions & KIND_ALLOW_LIST.get(self.kind, frozenset())


@dataclass(frozen=True, slots=True)
class Assignment:
    """A staff member holds a sub-role over a scope until it expires or is revoked."""

    id: UUID
    user_id: UUID
    role: StaffRole
    scope_kind: ScopeKind
    scope_ref: UUID | None
    starts_at: dt.datetime
    expires_at: dt.datetime | None
    granted_by: UUID | None
    granted_via: GrantedVia = "admin"
    parent_assignment_id: UUID | None = None
    revoked_at: dt.datetime | None = None

    def active_at(self, now: dt.datetime) -> bool:
        """Return whether the assignment is in force at `now`."""
        if self.revoked_at is not None or self.role.archived_at is not None:
            return False
        if self.starts_at > now:
            return False
        return self.expires_at is None or self.expires_at > now

    def covers(self, student_id: UUID, student_groups: Collection[UUID]) -> bool:
        """Return whether the scope covers the student."""
        if self.scope_kind == "all":
            return True
        if self.scope_kind == "student":
            return self.scope_ref == student_id
        return self.scope_ref is not None and self.scope_ref in student_groups


@dataclass(frozen=True, slots=True)
class StudentAccessFacts:
    """What the resolver needs to know about the student, read once per request."""

    student_id: UUID
    group_ids: frozenset[UUID] = frozenset()
    staff_view_consent: bool = False
    mentee_opt_in: bool = False
    entitled: bool = False


@dataclass(frozen=True, slots=True)
class ActorFacts:
    """What the resolver needs to know about the actor."""

    user_id: UUID
    active: bool
    roles: frozenset[Role]
    mentor_opt_in: bool = False
    assignments: tuple[Assignment, ...] = ()
    helper_of: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class Resolution:
    """Effective permissions; `in_scope` separates 404 from 403."""

    permissions: frozenset[Permission]
    in_scope: bool
    owner: bool = False
    limited: bool = False
    via: tuple[UUID, ...] = field(default=())


def _live(actor: ActorFacts, now: dt.datetime) -> list[Assignment]:
    """Assignments in force whose global role the actor currently holds."""
    return [
        a
        for a in actor.assignments
        if a.active_at(now) and KIND_ROLE.get(a.role.kind) in actor.roles
    ]


def _covering(
    actor: ActorFacts, student: StudentAccessFacts, now: dt.datetime
) -> list[Assignment]:
    """Live assignments that cover the student (mentors need both opt-ins)."""
    mentor_ok = student.mentee_opt_in and actor.mentor_opt_in
    return [
        a
        for a in _live(actor, now)
        if a.covers(student.student_id, student.group_ids)
        and (a.role.kind != "mentor" or mentor_ok)
    ]


def resolve(
    actor: ActorFacts, student: StudentAccessFacts, now: dt.datetime
) -> Resolution:
    """Return the actor's permissions over one student (§4.4, steps 1–6)."""
    if not actor.active:
        return Resolution(frozenset(), in_scope=False)
    if actor.user_id == student.student_id:
        if student.entitled:
            return Resolution(OWNER_SET, in_scope=True, owner=True)
        return Resolution(frozenset(), in_scope=False)
    covered = _covering(actor, student, now)
    perms: set[Permission] = set()
    for a in covered:
        perms |= a.role.effective_permissions
    covering = bool(covered)
    limited = covering and not student.staff_view_consent
    if limited:
        perms &= NO_CONSENT_SET
    if student.student_id in actor.helper_of:
        covering = True
        perms |= HELPER_SET
    return Resolution(
        frozenset(perms),
        in_scope=covering,
        limited=limited,
        via=tuple(a.id for a in covered),
    )


def scope_rank(kind: ScopeKind) -> int:
    """Order scopes from narrow to wide."""
    return {"student": 0, "cohort": 1, "all": 2}[kind]


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """A counselor asks to give `target` a sub-role over a scope."""

    target_user_id: UUID
    target_roles: frozenset[Role]
    target_active: bool
    target_mentor_opt_in: bool
    role: StaffRole
    scope_kind: ScopeKind
    scope_ref: UUID | None
    expires_at: dt.datetime | None
    # Students covered by the requested scope with their mentee opt-in.
    targets: tuple[StudentAccessFacts, ...]


DelegationDenial = Literal[
    "self",
    "not_delegable",
    "kind_not_allowed",
    "target_role",
    "target_inactive",
    "mentor_opt_in",
    "mentee_opt_in",
    "scope",
    "superset",
    "expiry",
    "no_grant",
]


def _request_denial(
    grantor: ActorFacts, request: DelegationRequest
) -> DelegationDenial | None:
    """Denial from the role and the target alone, before looking at scopes."""
    role = request.role
    if request.target_user_id == grantor.user_id:
        return "self"
    if role.permissions & NOT_DELEGABLE:
        return "not_delegable"
    if role.permissions - KIND_ALLOW_LIST.get(role.kind, frozenset()):
        return "kind_not_allowed"
    if KIND_ROLE.get(role.kind) not in request.target_roles:
        return "target_role"
    if not request.target_active:
        return "target_inactive"
    if role.kind == "mentor" and not request.target_mentor_opt_in:
        return "mentor_opt_in"
    return None


def _targets_parent(
    grantor: ActorFacts,
    request: DelegationRequest,
    live: list[Assignment],
    now: dt.datetime,
) -> tuple[DelegationDenial | None, Assignment | None]:
    """Check every target student; return the widest covering parent assignment."""
    role = request.role
    parent: Assignment | None = None
    for student in request.targets:
        if role.kind == "mentor" and not student.mentee_opt_in:
            return "mentee_opt_in", None
        effective = resolve(grantor, student, now)
        if not effective.in_scope or not role.permissions <= effective.permissions:
            return "superset", None
        covering = [a for a in live if a.covers(student.student_id, student.group_ids)]
        if not covering:
            return "superset", None
        parent = parent or max(covering, key=lambda a: scope_rank(a.scope_kind))
    return None, parent


def can_delegate(
    grantor: ActorFacts, request: DelegationRequest, now: dt.datetime
) -> tuple[DelegationDenial | None, Assignment | None]:
    """Check §4.5; return the denial reason or the parent assignment to cite."""
    denial = _request_denial(grantor, request)
    if denial is not None:
        return denial, None
    live = [
        a
        for a in _live(grantor, now)
        if Permission.STUDENTS_ASSIGN in a.role.effective_permissions
    ]
    if not live:
        return "no_grant", None
    holds_all = any(a.scope_kind == "all" for a in live)
    if request.scope_kind == "all" or (
        request.scope_kind == "cohort" and not holds_all
    ):
        return "scope", None
    if not request.targets:
        return "scope", None
    denial, parent = _targets_parent(grantor, request, live, now)
    if denial is not None:
        return denial, None
    assert parent is not None
    if parent.expires_at is not None and (
        request.expires_at is None or request.expires_at > parent.expires_at
    ):
        return "expiry", None
    return None, parent


def cascade_revoke(assignments: Iterable[Assignment], revoked_id: UUID) -> list[UUID]:
    """Return ids of the delegated descendants of `revoked_id` (breadth first)."""
    children: dict[UUID, list[UUID]] = {}
    for a in assignments:
        if a.parent_assignment_id is not None and a.revoked_at is None:
            children.setdefault(a.parent_assignment_id, []).append(a.id)
    out: list[UUID] = []
    queue = [revoked_id]
    while queue:
        for child in children.get(queue.pop(0), []):
            out.append(child)
            queue.append(child)
    return out
