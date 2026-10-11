"""Check a passwordless login code with its failure limits (ID-15)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import LOGIN_FAILED
from app.modules.identity.domain.errors import OtpInvalidError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.base_error import RateLimitedError


@dataclass(frozen=True, slots=True)
class PasswordlessOtpCheck:
    """Shared by the web OTP login and the Telegram mini app login."""

    otp: OtpService
    throttle: LoginThrottle
    failures_per_day: int

    async def execute(
        self, uow: IdentityUnitOfWorkPort, login: str, code: str, ctx: RequestContext
    ) -> User:
        """Return the user whose code is right; Administration is never accepted."""
        ip = ctx.throttle_ip
        user = await uow.users.get_by_login(login)
        if user is None or not user.is_active or not user.otp_enabled or user.is_admin:
            raise await self.failure("login", login, ip)
        failures = await self.throttle.otp_failures(user.id, ip)
        if failures >= self.failures_per_day:
            raise RateLimitedError(params={"retry_after": 3600})
        try:
            await self.otp.check("login", str(user.id), code)
        except OtpInvalidError:
            await self.throttle.record_otp_failure(user.id, ip)
            uow.audit(make_audit(LOGIN_FAILED, user_id=user.id, ctx=ctx, reason="otp"))
            await uow.commit()
            raise await self.failure("login", login, ip) from None
        await self.throttle.reset_code_failures("login", login, ip)
        return user

    async def failure(self, purpose: str, login: str, ip: str) -> OtpInvalidError:
        """The error for a wrong code; ``attempts_left`` is the same for any login."""
        left = await self.throttle.record_code_failure(purpose, login, ip)
        return OtpInvalidError(params={"attempts_left": left})
