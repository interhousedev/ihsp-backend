"""POST /v1/id/recovery/password/confirm: set a new password with the emailed code."""

from dataclasses import dataclass

from app.modules.identity.application.accept_login_for_user import LoginAcceptorImpl
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import enable_password_login
from app.modules.identity.application.find_user_for_recovery import (
    find_user_for_recovery,
)
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.recovery_confirm_limits import (
    code_failure,
    limit_confirms,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import PASSWORD_RESET
from app.modules.identity.domain.errors import OtpInvalidError, PasswordPolicyError
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class ConfirmPasswordReset:
    """Changes the password, logs the user out everywhere, then back in here."""

    uow_factory: UowFactory
    otp: OtpService
    hasher: PasswordHasher
    revoker: AccessRevoker
    rate_limiter: RateLimiter
    throttle: LoginThrottle
    login_acceptor: LoginAcceptorImpl

    async def execute(
        self, login_or_email: str, code: str, new_password: str, ctx: RequestContext
    ) -> str:
        """Verify, save, revoke everything; return a one-time sign-in ticket.

        The browser that proved the code redeems the ticket on IHT ID's next login
        challenge, so the reset ends signed in on this device only.
        """
        ip = ctx.throttle_ip
        await self.rate_limiter.hit(f"recovery-ip:{ip}", limit=20, window_seconds=3600)
        await limit_confirms(self.rate_limiter, login_or_email)
        errors = check_password(new_password)
        if errors:
            raise PasswordPolicyError(params={"errors": errors})
        async with self.uow_factory() as uow:
            user = await find_user_for_recovery(uow, login_or_email)
            if user is None:
                raise await code_failure(self.throttle, "pw-reset", login_or_email, ip)
            try:
                await self.otp.check("pw-reset", str(user.id), code)
            except OtpInvalidError:
                raise await code_failure(
                    self.throttle, "pw-reset", login_or_email, ip
                ) from None
            await self.throttle.reset_code_failures("pw-reset", login_or_email, ip)
            user.password_hash = await self.hasher.hash(new_password)
            user.password_change_required = False
            await enable_password_login(uow, user.id)
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            uow.audit(make_audit(PASSWORD_RESET, user_id=user.id, ctx=ctx))
            await uow.commit()
        return await self.login_acceptor.issue_ticket(user.id, amr=["pwd"])
