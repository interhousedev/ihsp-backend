"""MailSuspension for the mail module, backed by the identity user record."""

from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.domain.audit_event import MAIL_SUSPENDED
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType


class MailSuspensionAdapter:
    """Mail ← identity: reads and sets `users.mail_suspended_at` (MAIL-8)."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Keep the identity unit of work factory and the clock."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def is_suspended(self, user_id: UUID) -> bool:
        """True while `mail_suspended_at` is set."""
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
        return user is not None and user.mail_suspended_at is not None

    async def suspend(self, user_id: UUID, reason: str) -> None:
        """Suspend sending automatically; the user is told why."""
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or user.mail_suspended_at is not None:
                return
            now = self._clock.now()
            user.mail_suspended_at = now
            await uow.users.save(user)
            uow.notify(
                NotificationDraft(
                    user_id=user_id,
                    type=NotificationType.MAIL_SUSPENDED,
                    payload={"reason": reason},
                    dedupe_key=f"mail-suspended:{user_id}:{int(now.timestamp())}",
                )
            )
            uow.audit(make_audit(MAIL_SUSPENDED, user_id=user_id, reason=reason))
            await uow.commit()
