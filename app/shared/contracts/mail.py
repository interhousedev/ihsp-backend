"""Mail contracts (provider: mail module; consumer: bot)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MailSummary:
    """A mail in a list."""

    id: UUID
    direction: Literal["in", "out"]
    from_address: str
    to: tuple[str, ...]
    subject: str
    snippet: str
    occurred_at: datetime
    purged: bool


class MailApi(Protocol):
    """Mailbox operations for other modules."""

    async def recent(
        self, user_id: UUID, *, limit: int = 10, before: datetime | None = None
    ) -> list[MailSummary]:
        """Return the newest mails of the user."""
        ...

    async def view(self, user_id: UUID, mail_id: UUID) -> dict[str, Any]:
        """Return {"summary", "text", "html_telegram", "attachments", "truncated"}."""
        ...

    async def send(
        self, user_id: UUID, *, to: Sequence[str], subject: str, html: str
    ) -> MailSummary:
        """Send a new mail."""
        ...

    async def reply(self, user_id: UUID, mail_id: UUID, *, html: str) -> MailSummary:
        """Reply to a mail."""
        ...

    async def forward(
        self,
        user_id: UUID,
        mail_id: UUID,
        *,
        to: Sequence[str],
        note_html: str | None,
    ) -> MailSummary:
        """Forward a mail."""
        ...

    async def mark_spam(self, user_id: UUID, mail_id: UUID, *, spam: bool) -> None:
        """Mark or unmark a mail as spam."""
        ...

    def address_of(self, login: str) -> str:
        """Return the user's mail address."""
        ...
