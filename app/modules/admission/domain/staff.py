"""Staff caseload, delegation, comments and the student's audit view."""

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import DelegationDeniedError
from app.modules.admission.domain.permissions import (
    KIND_ROLE,
    NOT_DELEGABLE,
    Permission,
)

MAX_SAVED_VIEWS: Final = 20
MAX_VIEW_NAME: Final = 60
VIEW_FILTER_KEYS: Final = frozenset({"stage", "risk", "deadline_before", "group_id"})
"""Keys a saved view may keep; anything else is rejected."""

COMMENT_PERMISSION: Final[dict[str, Permission]] = {
    "profile": Permission.PROFILE_COMMENT,
    "help_request": Permission.PROFILE_COMMENT,
    "item": Permission.ACTIVITIES_COMMENT,
    "list_entry": Permission.LIST_COMMENT,
    "essay": Permission.ESSAYS_COMMENT,
    "words": Permission.WORDS_COMMENT,
}
"""The permission that lets staff comment on each kind of target."""


@dataclass(frozen=True, slots=True)
class CaseloadRow:
    """One student on a staff member's list."""

    student_id: UUID
    stage: str | None
    next_due: dt.datetime | None
    overdue: int
    open_help: int
    group_name: str | None = None


@dataclass(frozen=True, slots=True)
class SavedView:
    """A saved filter of the caseload."""

    id: UUID
    user_id: UUID
    name: str
    filters: dict[str, Any] = field(default_factory=dict)
    sort: str | None = None
    is_default: bool = False
    lock_version: int = 1


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment on a student's object."""

    id: UUID
    student_id: UUID
    target_kind: str
    target_id: UUID
    author_id: UUID
    body: str
    visibility: str
    created_at: dt.datetime
    anchor: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One access to a student's data, as the student sees it."""

    at: dt.datetime
    actor_kind: str
    action: str
    object_type: str | None
    object_id: UUID | None
    staff_role_id: UUID | None


@dataclass(frozen=True, slots=True)
class StaffUser:
    """The target of an assignment."""

    user_id: UUID
    roles: frozenset[str]
    active: bool


def deny(reason: str) -> DelegationDeniedError:
    """Return the delegation error with its reason."""
    return DelegationDeniedError(params={"reason": reason})


def _check_request(
    grantor_id: UUID,
    target_user: StaffUser | None,
    role: StaffRole,
    scope_kind: str,
    scope_ref: UUID | None,
    student_id: UUID | None,
) -> None:
    """Raise the denial that the request itself deserves, before any parent."""
    if target_user is None or target_user.user_id == grantor_id:
        raise deny("target")
    if not target_user.active:
        raise deny("inactive")
    needed = KIND_ROLE.get(role.kind)
    if needed is None or needed.value not in target_user.roles:
        raise deny("global_role")
    if role.effective_permissions & NOT_DELEGABLE:
        raise deny("not_delegable")
    if scope_kind == "all":
        raise deny("scope")
    if scope_kind == "student" and (scope_ref is None or scope_ref != student_id):
        raise deny("scope")


def pick_parent(
    grantor_id: UUID,
    grantor_roles: Collection[Assignment],
    target_user: StaffUser | None,
    role: StaffRole,
    scope_kind: str,
    scope_ref: UUID | None,
    expires_at: dt.datetime | None,
    student_groups: Collection[UUID],
    student_id: UUID | None,
    now: dt.datetime,
) -> Assignment:
    """Return the grantor's assignment that lets them delegate the request.

    `grantor_roles` are the grantor's live assignments holding `students:assign`.
    Raises DelegationDeniedError(reason=...) when none qualifies.
    """
    _check_request(grantor_id, target_user, role, scope_kind, scope_ref, student_id)
    reason = "scope"
    for parent in grantor_roles:
        if not parent.active_at(now):
            continue
        if scope_kind == "cohort":
            if parent.scope_kind != "all":
                continue
        elif student_id is None or not parent.covers(student_id, student_groups):
            continue
        reason = "permissions"
        if not role.effective_permissions <= parent.role.effective_permissions:
            continue
        reason = "expiry"
        if parent.expires_at is not None and (
            expires_at is None or expires_at > parent.expires_at
        ):
            continue
        return parent
    raise deny(reason)
