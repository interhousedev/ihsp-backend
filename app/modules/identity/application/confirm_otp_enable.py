"""POST /v1/id/me/otp/enable/confirm: turn OTP login on after the test code."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OTP_ENABLED
from app.modules.identity.domain.errors import OtpInvalidError
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class ConfirmOtpEnable:
    """Second step of UF-ID-06."""

    uow_factory: UowFactory
    otp: OtpService
    tickets: TicketStore

    async def execute(self, actor: Actor, code: str, ctx: RequestContext) -> None:
        """Verify the code and switch OTP login on with the chosen channels."""
        key = f"otp-enable:{actor.user_id}"
        pending = await self.tickets.get(key)
        if pending is None:
            raise OtpInvalidError(params={"attempts_left": 0})
        await self.otp.check("otp-enable", str(actor.user_id), code)
        await self.tickets.delete(key)
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            user.otp_enabled = True
            user.otp_via_email = bool(pending.get("via_email"))
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    OTP_ENABLED,
                    user_id=user.id,
                    ctx=ctx,
                    via_email=user.otp_via_email,
                )
            )
            await uow.commit()
