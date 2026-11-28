"""Ownership transfer between two members."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.modules.activities.domain.errors import Conflict
from app.modules.activities.domain.membership import MemberRole, Membership

__all__ = ["TRANSFER_TTL", "OwnershipTransfer", "TransferError", "TransferStatus"]

TRANSFER_TTL = timedelta(days=7)


class TransferStatus(StrEnum):
    """Transfer lifecycle."""

    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TransferError(Conflict):
    """The transfer cannot proceed."""


@dataclass(slots=True)
class OwnershipTransfer:
    """An offer to hand a club over."""

    club_id: UUID
    from_user: UUID
    to_user: UUID
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    status: TransferStatus = TransferStatus.OFFERED

    @classmethod
    def offer(
        cls,
        club_id: UUID,
        from_user: UUID,
        to_user: UUID,
        now: datetime,
        to_is_active_member: bool,
    ) -> "OwnershipTransfer":
        """Offer the club to an active member."""
        if from_user == to_user or not to_is_active_member:
            raise TransferError()
        return cls(club_id, from_user, to_user, now + TRANSFER_TTL)

    def _open(self) -> None:
        if self.status != TransferStatus.OFFERED:
            raise TransferError()

    def accept(self, now: datetime, members: dict[UUID, Membership]) -> None:
        """Swap roles; nothing changes when any check fails."""
        self._open()
        if now > self.expires_at:
            raise TransferError()
        owner, target = members.get(self.from_user), members.get(self.to_user)
        if (
            owner is None
            or target is None
            or not owner.is_active
            or not target.is_active
            or owner.role != MemberRole.OWNER
        ):
            raise TransferError()
        owner.role = MemberRole.CO_OWNER
        target.role = MemberRole.OWNER
        self.status = TransferStatus.ACCEPTED

    def decline(self) -> None:
        """The recipient says no."""
        self._open()
        self.status = TransferStatus.DECLINED

    def cancel(self) -> None:
        """The owner withdraws the offer."""
        self._open()
        self.status = TransferStatus.CANCELLED

    def expire(self, now: datetime) -> None:
        """Close an offer past its deadline."""
        if self.status == TransferStatus.OFFERED and now > self.expires_at:
            self.status = TransferStatus.EXPIRED
