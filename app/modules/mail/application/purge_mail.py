"""Daily cleanup of old mail (MAIL-5, MAIL-7)."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.mail.application.config import MailConfig
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """How many rows were deleted and how many were flagged as purged."""

    spam_deleted: int
    flagged: int


class PurgeMail:
    """Delete old spam; flag old mails (B6's expiry deletes their files)."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, config: MailConfig
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._config = config

    async def execute(self) -> PurgeResult:
        """Run both cleanups in one transaction."""
        cutoff = self._clock.now() - timedelta(days=self._config.retention_days)
        async with self._uow_factory() as uow:
            deleted = await uow.mail.delete_spam_before(cutoff)
            flagged = await uow.mail.flag_purged_before(cutoff)
            await uow.commit()
        return PurgeResult(spam_deleted=deleted, flagged=flagged)
