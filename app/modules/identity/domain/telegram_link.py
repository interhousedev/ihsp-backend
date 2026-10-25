"""A linked Telegram account."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.shared.contracts.identity import TelegramAccountRef


@dataclass(slots=True)
class TelegramLink:
    """Deleting the link unlinks the account and logs it out of the bot."""

    telegram_user_id: int
    user_id: UUID
    first_name: str
    otp_delivery: bool = True
    username: str | None = None
    blocked_at: datetime | None = None
    last_seen_at: datetime | None = None
    linked_at: datetime | None = None

    @property
    def can_receive_otp(self) -> bool:
        """True when codes may be sent to this account."""
        return self.otp_delivery and self.blocked_at is None

    def to_ref(self) -> TelegramAccountRef:
        """Read-only view for other modules."""
        return TelegramAccountRef(
            telegram_user_id=self.telegram_user_id,
            user_id=self.user_id,
            otp_delivery=self.otp_delivery,
            username=self.username,
            blocked=self.blocked_at is not None,
        )
