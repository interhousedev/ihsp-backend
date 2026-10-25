"""POST /v1/admin/users/{id}/mail/suspend: stop a mailbox from sending (MAIL-8)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import MAIL_SUSPENDED
from app.modules.identity.domain.user import User
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType


@dataclass(frozen=True, slots=True)
class SuspendMail:
    """Receiving keeps working; the user is told why sending stopped."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(
        self, actor: Actor, user_id: UUID, reason: str, ctx: RequestContext
    ) -> User:
        """Mark the mailbox suspended."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, user_id)
            now = self.clock.now()
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
            uow.audit(
                make_audit(
                    MAIL_SUSPENDED,
                    user_id=user_id,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    reason=reason,
                )
            )
            await uow.commit()
        return user
