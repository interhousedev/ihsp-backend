"""POST /v1/id/login/otp/request: send a login code, always answering the same."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpChannelMissingError
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.rate_limit import RateLimiter

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequestLoginOtp:
    """Passwordless codes (ID-13, ID-15): the caller learns nothing about accounts."""

    uow_factory: UowFactory
    otp: OtpService
    throttle: LoginThrottle
    rate_limiter: RateLimiter
    clock: Clock
    codes_per_hour: int
    failures_per_day: int

    async def execute(self, login: str, ctx: RequestContext) -> None:
        """Send a code if the account allows it; otherwise do nothing, silently."""
        ip = ctx.throttle_ip
        async with self.uow_factory() as uow:
            user = await uow.users.get_by_login(login)
            # A pending deletion may sign in with a code to restore the account.
            usable = user is not None and (user.is_active or user.is_pending_deletion)
            if user is None or not usable or not user.otp_enabled:
                return
            if user.is_admin:  # Administration needs the password first (ID-11)
                return
            if await self.throttle.otp_failures(user.id, ip) >= self.failures_per_day:
                return
            try:
                await self.rate_limiter.hit(
                    f"otp:{user.id}:{ip}",
                    limit=self.codes_per_hour,
                    window_seconds=3600,
                )
            except RateLimitedError:
                await self._notify_limit(uow, user.id, ctx)
                return
            links = await uow.telegram_links.list_for_user(user.id)
            try:
                await self.otp.send(
                    user, links, purpose="login", subject_key=str(user.id), ctx=ctx
                )
            except (RateLimitedError, OtpChannelMissingError):
                log.info("login_otp_not_sent", user_id=str(user.id))

    async def _notify_limit(
        self, uow: IdentityUnitOfWorkPort, user_id: UUID, ctx: RequestContext
    ) -> None:
        hour = self.clock.now().strftime("%Y%m%d%H")
        uow.notify(
            NotificationDraft(
                user_id=user_id,
                type=NotificationType.LOGIN_FAILURES,
                payload={"count": self.codes_per_hour, "ip": ctx.valid_ip},
                dedupe_key=f"otp-limit:{user_id}:{hour}",
            )
        )
        await uow.commit()
