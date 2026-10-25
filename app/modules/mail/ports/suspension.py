"""Sending suspension of a mailbox (MAIL-8); implemented by I1 over identity."""

from typing import Protocol
from uuid import UUID


class MailSuspensionReader(Protocol):
    """Tells whether sending from a user's mailbox is suspended."""

    async def is_suspended(self, user_id: UUID) -> bool:
        """True while ``users.mail_suspended_at`` is set."""
        ...


class MailSuspender(Protocol):
    """Suspends sending (the automatic path of MAIL-8)."""

    async def suspend(self, user_id: UUID, reason: str) -> None:
        """Set the suspension with the reason."""
        ...


class MailSuspension(MailSuspensionReader, MailSuspender, Protocol):
    """Both halves, as one object for wiring."""
