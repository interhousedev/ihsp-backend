"""POST /v1/id/recovery/otp/cancel: the Cancel button in Telegram."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.notice_email import send_notice
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OTP_RESET_CANCELLED
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class CancelOtpReset:
    """Stops a pending reset; an unknown request id is ignored silently."""

    uow_factory: UowFactory
    email: EmailSender

    async def execute(self, request_id: UUID, ctx: RequestContext) -> None:
        """Clear the pending reset and tell the owner to change the password."""
        async with self.uow_factory() as uow:
            user = await uow.users.get_by_otp_reset_request(request_id)
            if user is None:
                return
            user.clear_otp_reset()
            await uow.users.save(user)
            uow.audit(make_audit(OTP_RESET_CANCELLED, user_id=user.id, ctx=ctx))
            await uow.commit()
        await send_notice(
            self.email, user.recovery_email, user.locale, "id-mail-notice-otp-cancelled"
        )
