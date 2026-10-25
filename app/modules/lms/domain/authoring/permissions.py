"""Course staff permissions and role presets (LMS-5, LMS-21)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.modules.lms.domain.authoring.entities import StaffMember
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    StaffInvalidError,
)
from app.shared.actor import Actor, Role
from app.shared.lms_scopes import scope_allows, scope_allows_read

EDIT: Final = "edit"
PUBLISH: Final = "publish"
REVIEW: Final = "review"
MANAGE_STAFF: Final = "manage_staff"
VIEW_DRAFTS: Final = "view_drafts"

PERMISSION_ORDER: Final = (EDIT, PUBLISH, REVIEW, MANAGE_STAFF, VIEW_DRAFTS)
PERMISSIONS: Final = frozenset(PERMISSION_ORDER)

ROLE_PRESETS: Final[dict[str, frozenset[str]]] = {
    "owner": PERMISSIONS,
    "teacher": frozenset({EDIT, PUBLISH, REVIEW, VIEW_DRAFTS}),
    "reviewer": frozenset({REVIEW}),
    "support": frozenset({REVIEW}),
    "tester": frozenset({VIEW_DRAFTS}),
}

ROLE_MAX_LENGTH: Final = 40


def ordered(values: Iterable[str]) -> list[str]:
    """Return the permissions in the canonical order, without duplicates."""
    present = set(values)
    return [p for p in PERMISSION_ORDER if p in present]


def preset_permissions(role: str) -> list[str] | None:
    """Return the preset permissions for a role name, if the name is a preset."""
    preset = ROLE_PRESETS.get(role.strip().lower())
    return None if preset is None else ordered(preset)


def normalize_permissions(values: Iterable[str]) -> list[str]:
    """Validate that every value is a known permission; return them ordered."""
    items = list(values)
    unknown = sorted(set(items) - PERMISSIONS)
    if unknown:
        raise StaffInvalidError(params={"unknown": unknown})
    return ordered(items)


def normalize_role(role: str) -> str:
    """Trim the role label and check its length (1-40 characters)."""
    label = role.strip()
    if not 1 <= len(label) <= ROLE_MAX_LENGTH:
        raise StaffInvalidError(params={"max_length": ROLE_MAX_LENGTH})
    return label


@dataclass(frozen=True, slots=True)
class CourseAccess:
    """What an actor may do in one course: the LMS admin can do everything."""

    actor: Actor
    staff: StaffMember | None

    @property
    def is_admin(self) -> bool:
        """Return True for LMS administrators."""
        return self.actor.has(Role.LMS_ADMIN)

    @property
    def is_staff(self) -> bool:
        """Return True for the LMS admin and for course staff."""
        return self.is_admin or self.staff is not None

    @property
    def permissions(self) -> list[str]:
        """Permissions of the actor in this course, in canonical order."""
        if self.is_admin:
            return list(PERMISSION_ORDER)
        return ordered(self.staff.permissions) if self.staff else []

    def can(self, permission: str) -> bool:
        """Return True if the actor holds the permission."""
        return self.is_admin or permission in self.permissions

    def require(self, *permissions: str) -> None:
        """Raise CoursePermissionError unless the actor holds one of them."""
        if not any(self.can(p) for p in permissions):
            raise CoursePermissionError(params={"permission": permissions[0]})

    def require_staff(self) -> None:
        """Raise CoursePermissionError unless the actor is course staff."""
        if not self.is_staff:
            raise CoursePermissionError(params={"permission": "staff"})

    def require_scope(self, scope: str) -> None:
        """Raise CoursePermissionError unless the caller's token grants the scope.

        Scopes narrow roles, they never widen them: an LMS admin whose connector
        holds only `lms.modules.write` still cannot change a course title. A browser
        session has no scopes and passes.
        """
        if not scope_allows(self.actor.scopes, scope):
            raise CoursePermissionError(params={"permission": scope})

    def require_read_scope(self) -> None:
        """Raise CoursePermissionError unless the token holds any LMS scope."""
        if not scope_allows_read(self.actor.scopes):
            raise CoursePermissionError(params={"permission": "lms.courses.read"})
