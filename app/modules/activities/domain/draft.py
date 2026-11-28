"""Volunteer drafting: club profiles, rounds, signups and picks."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.domain.club import (
    CapabilityDisabledError,
    Club,
    ClubCapability,
)
from app.modules.activities.domain.errors import Conflict, Denied, Invalid

__all__ = [
    "CapabilityDisabledError",
    "ClubProfile",
    "DraftInvalidError",
    "DraftPick",
    "DraftPickStateError",
    "DraftRound",
    "DraftSignup",
    "DuplicateSignupError",
    "NotClubMemberError",
    "RoleFullError",
    "RoundClosedError",
]


class DraftInvalidError(Invalid):
    """A draft input is invalid."""


class DuplicateSignupError(Conflict):
    """The person already signed up for this round."""


class NotClubMemberError(Denied):
    """Only active members take part."""


class RoundClosedError(Conflict):
    """The round no longer takes signups."""


class RoleFullError(Conflict):
    """Every slot of the role is taken."""


class DraftPickStateError(Conflict):
    """The pick is not in a state that allows this."""


@dataclass(slots=True)
class ClubProfile:
    """A member's reusable answers for one club."""

    user_id: UUID
    club_id: UUID
    answers: dict[str, Any]
    updated_at: datetime

    def upsert(self, answers: dict[str, Any], now: datetime) -> None:
        """Replace the answers."""
        self.answers = dict(answers)
        self.updated_at = now


@dataclass(slots=True)
class DraftRound:
    """A call for volunteers for one event of the club."""

    event_id: UUID
    club_id: UUID
    needed: dict[str, int]
    id: UUID = field(default_factory=uuid4)
    status: str = "open"

    @classmethod
    def open(
        cls,
        event_id: UUID,
        club_id: UUID,
        needed: dict[str, int],
        *,
        club: Club,
        event_club_id: UUID,
    ) -> "DraftRound":
        """Open a round; needs the drafting capability and the club's own event."""
        club.require(ClubCapability.DRAFTING)
        if event_club_id != club_id or club.id != club_id:
            raise DraftInvalidError(params={"field": "event_id"})
        if not needed or any(n < 1 for n in needed.values()):
            raise DraftInvalidError(params={"field": "needed"})
        return cls(event_id, club_id, dict(needed))

    def close(self) -> None:
        """Stop taking signups."""
        self.status = "closed"


@dataclass(slots=True)
class DraftSignup:
    """A member offering to fill a role."""

    round_id: UUID
    user_id: UUID
    role: str
    answers: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    status: str = "submitted"

    @classmethod
    def submit(
        cls,
        rnd: DraftRound,
        user_id: UUID,
        role: str,
        answers: dict[str, Any],
        is_club_member: bool,
        existing: "list[DraftSignup] | tuple[DraftSignup, ...]" = (),
    ) -> "DraftSignup":
        """Sign up once per round; only active members, only for asked roles."""
        if rnd.status != "open":
            raise RoundClosedError()
        if not is_club_member:
            raise NotClubMemberError()
        if role not in rnd.needed:
            raise DraftInvalidError(params={"field": "role"})
        if any(
            s.user_id == user_id and s.round_id == rnd.id and s.status != "withdrawn"
            for s in existing
        ):
            raise DuplicateSignupError()
        return cls(rnd.id, user_id, role, dict(answers))

    def withdraw(self) -> None:
        """Take the signup back."""
        self.status = "withdrawn"


@dataclass(slots=True)
class DraftPick:
    """An organizer's choice of a volunteer for a role."""

    round_id: UUID
    user_id: UUID
    role: str
    id: UUID = field(default_factory=uuid4)
    status: str = "proposed"

    @classmethod
    def propose(
        cls, rnd: DraftRound, user_id: UUID, role: str, filled: dict[str, int]
    ) -> "DraftPick":
        """Pick someone while the role still has room."""
        if role not in rnd.needed:
            raise DraftInvalidError(params={"field": "role"})
        if filled.get(role, 0) >= rnd.needed[role]:
            raise RoleFullError()
        return cls(rnd.id, user_id, role)

    def _move(self, allowed: tuple[str, ...], to: str) -> None:
        if self.status not in allowed:
            raise DraftPickStateError(params={"status": self.status})
        self.status = to

    def invite(self) -> None:
        """Send the invitation."""
        self._move(("proposed",), "invited")

    def accept(self) -> None:
        """The volunteer accepts."""
        self._move(("invited",), "accepted")

    def decline(self) -> None:
        """The volunteer declines."""
        self._move(("invited",), "declined")

    def complete(self) -> None:
        """The shift was worked."""
        self._move(("accepted",), "completed")

    def mark_no_show(self) -> None:
        """The volunteer did not come."""
        self._move(("accepted",), "no_show")
