"""Port: delivering one-time codes to a user's channels."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.shared.contracts.identity import UserRef

CHANNEL_TELEGRAM = "telegram"
CHANNEL_EMAIL = "email"


@dataclass(frozen=True, slots=True)
class OtpContext:
    """Where the code was requested from (shown in the Telegram message)."""

    ip: str | None = None
    user_agent: str | None = None


class OtpSender(Protocol):
    """Sends a code through Telegram and/or email."""

    async def send_code(
        self,
        user: UserRef,
        code: str,
        *,
        purpose: str,
        channels: Sequence[str],
        context: OtpContext | None = None,
    ) -> None:
        """Deliver the code; a failing channel never blocks the others."""
        ...
