"""List the newest mails of a mailbox (MAIL-3)."""

from datetime import datetime
from uuid import UUID

from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.mail import MailSummary

MAX_LIMIT = 50


class RecentMail:
    """Newest first, spam hidden, paged by the time of the last item."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, limit: int, before: datetime | None
    ) -> list[MailSummary]:
        """Return up to ``limit`` summaries older than ``before``."""
        async with self._uow_factory() as uow:
            mails = await uow.mail.recent(
                user_id, limit=max(1, min(limit, MAX_LIMIT)), before=before
            )
        now = self._clock.now()
        return [mail.summary(now) for mail in mails]
