"""POST /v1/id/recovery/login: email the login to the recovery address (ID-26)."""

from dataclasses import dataclass

from app.modules.identity.application.find_user_for_recovery import (
    find_user_for_recovery,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.rate_limit import RateLimiter

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SendLoginReminder:
    """Neutral: the page always shows the same message."""

    uow_factory: UowFactory
    email: EmailSender
    rate_limiter: RateLimiter

    async def execute(self, address: str, ctx: RequestContext) -> None:
        """Send the login if the address is a verified recovery email."""
        await self.rate_limiter.hit(
            f"recovery-ip:{ctx.throttle_ip}", limit=20, window_seconds=3600
        )
        async with self.uow_factory() as uow:
            user = await find_user_for_recovery(uow, address, allow_admin=True)
        if user is None or not user.login or not user.recovery_email:
            return
        try:
            await self.rate_limiter.hit(
                f"login-reminder:{user.id}", limit=3, window_seconds=3600
            )
            await self.email.send(
                user.recovery_email,
                "login_reminder",
                {"login": user.login},
                user.locale,
            )
        except (RateLimitedError, EmailDeliveryError):
            log.info("login_reminder_not_sent", user_id=str(user.id))
