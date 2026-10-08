"""Suspend sending after a spike of bounces (MAIL-8, UF-ADM-15)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.mail.ports.suspension import MailSuspension
from app.modules.mail.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType

import structlog

log = structlog.get_logger(__name__)

BOUNCE_LIMIT = 5
BOUNCE_WINDOW = timedelta(hours=24)
SPIKE_REASON = "too many emails could not be delivered in 24 hours"
# The name identity uses for an administrator's suspension; "auto" tells them apart.
MAIL_SUSPENDED_AUDIT = "mail.suspended"


class CheckBounces:
    """Find mailboxes with at least five bounces in 24 hours and suspend them."""

    def __init__(
        self, *, uow_factory: UowFactory, suspension: MailSuspension, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._suspension = suspension
        self._clock = clock

    async def execute(self) -> list[UUID]:
        """Return the users suspended by this run."""
        since = self._clock.now() - BOUNCE_WINDOW
        async with self._uow_factory() as uow:
            counts = await uow.mail.users_with_bounces(since, BOUNCE_LIMIT)
        suspended: list[UUID] = []
        for user_id, count in counts.items():
            if await self._suspend(user_id, count, since):
                suspended.append(user_id)
        return suspended

    async def _suspend(self, user_id: UUID, count: int, since: datetime) -> bool:
        already = await self._suspension.is_suspended(user_id)
        if not already:
            await self._suspension.suspend(user_id, SPIKE_REASON)
        async with self._uow_factory() as uow:
            # Counted bounces never trigger a second suspension after a resume.
            await uow.mail.mark_bounces_counted(user_id, since)
            if not already:
                stamp = f"{self._clock.now():%Y%m%d%H}"
                uow.notify(
                    NotificationDraft(
                        user_id=user_id,
                        type=NotificationType.MAIL_SUSPENDED,
                        payload={"reason": SPIKE_REASON},
                        dedupe_key=f"mail-suspended:{user_id}:{stamp}",
                    )
                )
                uow.audit(
                    AuditDraft(
                        type=MAIL_SUSPENDED_AUDIT,
                        user_id=user_id,
                        metadata={
                            "auto": True,
                            "bounces": count,
                            "reason": SPIKE_REASON,
                        },
                    )
                )
            await uow.commit()
        log.warning("mailbox_suspended_by_bounces", user_id=str(user_id), bounces=count)
        return not already
