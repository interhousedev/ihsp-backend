"""List the mails the user sent from the platform (the Email page)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.mail.domain.mail_status import MailStatus
from app.modules.mail.ports.unit_of_work import UowFactory

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass(frozen=True, slots=True)
class SentMailItem:
    """One sent mail."""

    id: UUID
    to: tuple[str, ...]
    subject: str
    snippet: str
    sent_at: datetime
    status: MailStatus
    attachment_name: str | None


@dataclass(frozen=True, slots=True)
class SentMailPage:
    """A page of sent mails; ``next_before`` pages on."""

    items: list[SentMailItem]
    next_before: datetime | None


class ListSentMail:
    """Newest first, paged by the time of the last item."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_LIMIT,
        before: datetime | None = None,
    ) -> SentMailPage:
        """Return up to ``limit`` sent mails older than ``before``."""
        size = max(1, min(limit, MAX_LIMIT))
        async with self._uow_factory() as uow:
            rows = await uow.mail.sent(user_id, limit=size + 1, before=before)
        page, more = rows[:size], len(rows) > size
        items = [
            SentMailItem(
                id=row.id,
                to=tuple(row.to),
                subject=row.subject,
                snippet=row.snippet,
                sent_at=row.occurred_at,
                status=row.status,
                attachment_name=row.meta.attachment_name,
            )
            for row in page
        ]
        return SentMailPage(
            items=items,
            next_before=page[-1].occurred_at if more and page else None,
        )
