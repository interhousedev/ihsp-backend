"""POST /v1/id/recovery/otp/confirm: schedule the removal of Telegram links."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.find_user_for_recovery import (
    find_user_for_recovery,
)
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.recovery_confirm_limits import (
    code_failure,
    limit_confirms,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OTP_RESET_REQUESTED
from app.modules.identity.domain.errors import OtpInvalidError
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.rate_limit import RateLimiter

RESET_DELAY = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ConfirmOtpReset:
    """Starts the 24 hour countdown and warns every linked Telegram account."""

    uow_factory: UowFactory
    otp: OtpService
    clock: Clock
    rate_limiter: RateLimiter
    throttle: LoginThrottle

    async def execute(self, login: str, code: str, ctx: RequestContext) -> datetime:
        """Return when the reset takes effect."""
        ip = ctx.throttle_ip
        await self.rate_limiter.hit(f"recovery-ip:{ip}", limit=20, window_seconds=3600)
        await limit_confirms(self.rate_limiter, login)
        async with self.uow_factory() as uow:
            user = await find_user_for_recovery(uow, login)
            if user is None:
                raise await code_failure(self.throttle, "otp-reset", login, ip)
            try:
                await self.otp.check("otp-reset", str(user.id), code)
            except OtpInvalidError:
                raise await code_failure(
                    self.throttle, "otp-reset", login, ip
                ) from None
            await self.throttle.reset_code_failures("otp-reset", login, ip)
            request_id = new_id()
            effective_at = self.clock.now() + RESET_DELAY
            user.otp_reset_effective_at = effective_at
            user.otp_reset_request_id = request_id
            await uow.users.save(user)
            uow.notify(
                NotificationDraft(
                    user_id=user.id,
                    type=NotificationType.OTP_RESET_REQUESTED,
                    payload={
                        "effective_at": effective_at.isoformat(),
                        "request_id": str(request_id),
                    },
                    dedupe_key=f"otp-reset:{request_id}",
                )
            )
            uow.audit(
                make_audit(
                    OTP_RESET_REQUESTED,
                    user_id=user.id,
                    ctx=ctx,
                    effective_at=effective_at.isoformat(),
                )
            )
            await uow.commit()
        return effective_at
