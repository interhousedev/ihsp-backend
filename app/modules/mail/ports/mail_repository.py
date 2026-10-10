"""Persistence port of mailbox messages."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.mail.domain.mail_message import MailMessage


class MailRepository(Protocol):
    """Reads and writes mail rows; transactions belong to the unit of work."""

    async def add(self, mail: MailMessage) -> bool:
        """Insert the mail; False (nothing written) if the Message-ID is a duplicate."""
        ...

    async def get(self, mail_id: UUID) -> MailMessage | None:
        """Return the mail or None."""
        ...

    async def get_owned(self, user_id: UUID, mail_id: UUID) -> MailMessage | None:
        """Return the mail only if it is in this user's mailbox."""
        ...

    async def save(self, mail: MailMessage) -> None:
        """Write the changed fields of an existing row."""
        ...

    async def inbound_exists(self, user_id: UUID, message_id: str) -> bool:
        """True if the mailbox already has a received mail with this Message-ID."""
        ...

    async def recent(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailMessage]:
        """List non-spam mails, newest first, strictly older than ``before``."""
        ...

    async def sent(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailMessage]:
        """List the user's sent mails, newest first, strictly older than ``before``."""
        ...

    async def find_outbound(
        self, user_id: UUID, message_ids: Sequence[str]
    ) -> MailMessage | None:
        """Return the user's sent mail whose Message-ID is among the given ones."""
        ...

    async def unparsed_inbound(self, older_than: datetime, limit: int) -> list[UUID]:
        """Ids of received or spam mails not parsed yet and older than the moment."""
        ...

    async def stale_queued(self, older_than: datetime, limit: int) -> list[UUID]:
        """Ids of outbound mails still queued and older than the moment."""
        ...

    async def users_with_bounces(
        self, since: datetime, minimum: int
    ) -> dict[UUID, int]:
        """Uncounted bounces per user since the moment, for users with >= minimum."""
        ...

    async def mark_bounces_counted(self, user_id: UUID, since: datetime) -> None:
        """Flag the user's bounces since the moment as used for a suspension."""
        ...

    async def delete_spam_before(self, cutoff: datetime) -> int:
        """Delete spam rows received before the cutoff; return how many."""
        ...

    async def flag_purged_before(self, cutoff: datetime) -> int:
        """Set ``meta.purged`` on rows received before the cutoff; return how many."""
        ...
