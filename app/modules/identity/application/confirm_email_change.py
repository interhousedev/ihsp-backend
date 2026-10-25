"""POST /v1/id/me/email/change/confirm: switch the recovery email."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.notice_email import send_notice
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import EMAIL_CHANGED
from app.modules.identity.domain.errors import EmailTakenError, OtpInvalidError
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class ConfirmEmailChange:
    """Verifies the code, saves the email and warns the old address."""

    uow_factory: UowFactory
    otp: OtpService
    tickets: TicketStore
    email: EmailSender
    clock: Clock

    async def execute(self, actor: Actor, code: str, ctx: RequestContext) -> None:
        """Complete the change started by RequestEmailChange."""
        key = f"email-change:{actor.user_id}"
        pending = await self.tickets.get(key)
        if pending is None:
            raise OtpInvalidError(params={"attempts_left": 0})
        await self.otp.check("email-change", str(actor.user_id), code)
        await self.tickets.delete(key)
        new_email = str(pending["email"])
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if await uow.users.email_taken(new_email, except_user_id=user.id):
                raise EmailTakenError()
            old_email = user.recovery_email
            user.recovery_email = new_email
            user.recovery_email_verified_at = self.clock.now()
            await uow.users.save(user)
            uow.audit(
                make_audit(EMAIL_CHANGED, user_id=user.id, ctx=ctx, new_email=new_email)
            )
            await uow.commit()
        if old_email and old_email != new_email:
            await send_notice(
                self.email,
                old_email,
                user.locale,
                "id-mail-notice-email-changed",
                {"new_email": new_email},
            )
