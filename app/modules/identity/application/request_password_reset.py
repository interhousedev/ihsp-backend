"""POST /v1/id/recovery/password/request: code to the recovery email (ID-23)."""

from dataclasses import dataclass

from app.modules.identity.application.find_user_for_recovery import (
    find_user_for_recovery,
)
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.ports.otp_sender import CHANNEL_EMAIL
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.rate_limit import RateLimiter

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequestPasswordReset:
    """Always neutral: the caller learns nothing about the account."""

    uow_factory: UowFactory
    otp: OtpService
    rate_limiter: RateLimiter

    async def execute(self, login_or_email: str, ctx: RequestContext) -> None:
        """Send a code if the account qualifies (not Administration, email verified)."""
        await self.rate_limiter.hit(
            f"recovery-ip:{ctx.throttle_ip}", limit=20, window_seconds=3600
        )
        async with self.uow_factory() as uow:
            user = await find_user_for_recovery(uow, login_or_email)
            if user is None:
                return
            try:
                await self.rate_limiter.hit(
                    f"pw-reset:{user.id}", limit=5, window_seconds=3600
                )
                await self.otp.send(
                    user,
                    [],
                    purpose="pw-reset",
                    subject_key=str(user.id),
                    ctx=ctx,
                    channels=[CHANNEL_EMAIL],
                )
            except (RateLimitedError, EmailDeliveryError):
                log.info("password_reset_not_sent", user_id=str(user.id))
