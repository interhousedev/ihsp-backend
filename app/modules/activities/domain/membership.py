"""Club membership and joining."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.activities.domain.club import (
    Club,
    ClubStateError,
    ClubStatus,
    JoinPolicy,
)
from app.modules.activities.domain.errors import Conflict, Denied

__all__ = [
    "JoinNotAllowedError",
    "MemberRole",
    "MemberStatus",
    "Membership",
    "MembershipStateError",
    "NotStudentError",
    "OwnerCannotLeaveError",
    "join",
]


class MemberRole(StrEnum):
    """Role inside a club."""

    OWNER = "owner"
    CO_OWNER = "co_owner"
    TEAM = "team"
    MEMBER = "member"


class MemberStatus(StrEnum):
    """Membership lifecycle."""

    REQUESTED = "requested"
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"
    BANNED = "banned"


class JoinNotAllowedError(Denied):
    """The club takes members by invitation only."""


class NotStudentError(Denied):
    """Only students join clubs."""


class MembershipStateError(Conflict):
    """The membership is not in a state that allows this."""


class OwnerCannotLeaveError(Conflict):
    """The owner must transfer the club first."""


@dataclass(slots=True)
class Membership:
    """A person's place in a club."""

    club_id: UUID
    user_id: UUID
    role: MemberRole
    status: MemberStatus
    declaration_version: int
    joined_at: datetime | None
    left_at: datetime | None

    def approve(self, now: datetime) -> None:
        """Accept a join request."""
        if self.status != MemberStatus.REQUESTED:
            raise MembershipStateError()
        self.status = MemberStatus.ACTIVE
        self.joined_at = now

    def leave(self, now: datetime) -> None:
        """Leave the club."""
        if self.status != MemberStatus.ACTIVE:
            raise MembershipStateError()
        if self.role == MemberRole.OWNER:
            raise OwnerCannotLeaveError()
        self.status = MemberStatus.LEFT
        self.left_at = now

    def remove(self) -> None:
        """Remove the member."""
        self.status = MemberStatus.REMOVED

    def ban(self) -> None:
        """Ban the member for good."""
        self.status = MemberStatus.BANNED

    def can_rejoin(self) -> bool:
        """Banned people never rejoin."""
        return self.status != MemberStatus.BANNED

    @property
    def is_active(self) -> bool:
        """True while the person is a member."""
        return self.status == MemberStatus.ACTIVE


def join(
    club: Club,
    user_id: UUID,
    *,
    declaration_version: int,
    now: datetime,
    is_student: bool = True,
) -> Membership:
    """Join a club according to its policy; only an active club takes members."""
    if not is_student:
        raise NotStudentError()
    if club.status != ClubStatus.ACTIVE:
        raise ClubStateError(params={"status": str(club.status)})
    if club.join_policy == JoinPolicy.INVITE:
        raise JoinNotAllowedError()
    active = club.join_policy == JoinPolicy.OPEN
    return Membership(
        club.id,
        user_id,
        MemberRole.MEMBER,
        MemberStatus.ACTIVE if active else MemberStatus.REQUESTED,
        declaration_version,
        now if active else None,
        None,
    )
