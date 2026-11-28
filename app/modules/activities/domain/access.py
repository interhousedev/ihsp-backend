"""Permissions of club roles and global roles."""

from enum import StrEnum

from app.modules.activities.domain.errors import PermissionDeniedError
from app.modules.activities.domain.membership import MemberRole
from app.shared.actor import Role

__all__ = [
    "Permission",
    "PermissionDeniedError",
    "club_permissions",
    "global_permissions",
    "is_platform_staff",
]


class Permission(StrEnum):
    """What a person may do in a club."""

    VIEW_MEMBERS = "view_members"
    EDIT_CLUB = "edit_club"
    EDIT_EVENTS = "edit_events"
    ANNOUNCE = "announce"
    APPROVE = "approve"
    TRANSFER = "transfer"
    SEE_RATINGS_FULL = "see_ratings_full"
    MODERATE_MEDIA = "moderate_media"


_ALL = frozenset(Permission)


def club_permissions(
    role: MemberRole, *, announce_allowed: bool = False
) -> frozenset[Permission]:
    """Permissions a member role grants inside its own club."""
    if role == MemberRole.OWNER:
        return _ALL
    if role == MemberRole.CO_OWNER:
        return _ALL - {Permission.TRANSFER}
    if role == MemberRole.TEAM:
        base = {Permission.VIEW_MEMBERS, Permission.EDIT_EVENTS}
        if announce_allowed:
            base.add(Permission.ANNOUNCE)
        return frozenset(base)
    return frozenset({Permission.VIEW_MEMBERS})


def global_permissions(roles: frozenset[Role] | set[Role]) -> frozenset[Permission]:
    """Permissions the platform roles grant in every club."""
    out: set[Permission] = set()
    if Role.SU in roles:
        out |= {
            Permission.VIEW_MEMBERS,
            Permission.EDIT_CLUB,
            Permission.EDIT_EVENTS,
            Permission.ANNOUNCE,
            Permission.APPROVE,
            Permission.TRANSFER,
            Permission.MODERATE_MEDIA,
        }
    if Role.ACTIVITIES_ADMIN in roles or Role.ADMIN in roles:
        out |= {
            Permission.VIEW_MEMBERS,
            Permission.EDIT_CLUB,
            Permission.TRANSFER,
            Permission.SEE_RATINGS_FULL,
            Permission.MODERATE_MEDIA,
        }
    return frozenset(out)


def is_platform_staff(roles: frozenset[Role] | set[Role]) -> bool:
    """True for SU, ACTIVITIES_ADMIN and ADMIN (never derived from club ownership)."""
    return bool(roles & {Role.SU, Role.ACTIVITIES_ADMIN, Role.ADMIN})
