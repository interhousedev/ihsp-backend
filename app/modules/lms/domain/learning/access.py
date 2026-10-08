"""What an actor may do in a course on the learning side (LMS-8, LMS-20, LMS-21)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.modules.lms.domain.learning.entities import StaffMember
from app.modules.lms.domain.learning.errors import CoursePermissionError
from app.shared.actor import Actor, Role

REVIEW: Final = "review"
VIEW_DRAFTS: Final = "view_drafts"
EDIT: Final = "edit"

PERMISSION_ORDER: Final = ("edit", "publish", "review", "manage_staff", "view_drafts")


def ordered_permissions(values: Iterable[str]) -> list[str]:
    """Return the permissions in the canonical order, without unknown values."""
    present = set(values)
    return [permission for permission in PERMISSION_ORDER if permission in present]


@dataclass(frozen=True, slots=True)
class StaffAccess:
    """Course staff rights of an actor: the LMS admin can do everything."""

    actor: Actor
    member: StaffMember | None

    @property
    def is_admin(self) -> bool:
        """Return True for LMS administrators."""
        return self.actor.has(Role.LMS_ADMIN)

    @property
    def is_staff(self) -> bool:
        """Return True for the LMS admin and for course staff."""
        return self.is_admin or self.member is not None

    def can(self, permission: str) -> bool:
        """Return True if the actor holds the permission in the course."""
        if self.is_admin:
            return True
        return self.member is not None and permission in self.member.permissions

    def require(self, permission: str) -> None:
        """Raise CoursePermissionError unless the actor holds the permission."""
        if not self.can(permission):
            raise CoursePermissionError(params={"permission": permission})
