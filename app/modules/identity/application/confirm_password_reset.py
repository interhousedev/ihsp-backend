"""POST /v1/id/recovery/password/confirm: set a new password with the emailed code."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.find_user_for_recovery import (
    find_user_for_recovery,
)
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_access import AccessRevoker
from app.modules.identity.domain.audit_event import PASSWORD_RESET
from app.modules.identity.domain.errors import OtpInvalidError, PasswordPolicyError
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class ConfirmPasswordReset:
    """Changes the password and logs the user out everywhere."""

    uow_factory: UowFactory
    otp: OtpService
    hasher: PasswordHasher
    revoker: AccessRevoker
    rate_limiter: RateLimiter

    async def execute(
        self, login_or_email: str, code: str, new_password: str, ctx: RequestContext
    ) -> None:
        """Verify the code, apply the policy, save, revoke everything."""
        await self.rate_limiter.hit(
            f"recovery-ip:{ctx.throttle_ip}", limit=20, window_seconds=3600
        )
        errors = check_password(new_password)
        if errors:
            raise PasswordPolicyError(params={"errors": errors})
        async with self.uow_factory() as uow:
            user = await find_user_for_recovery(uow, login_or_email)
            if user is None:
                raise OtpInvalidError(params={"attempts_left": 0})
            await self.otp.check("pw-reset", str(user.id), code)
            user.password_hash = await self.hasher.hash(new_password)
            user.password_change_required = False
            await self.revoker.revoke_in(uow, user, keep_telegram=True)
            uow.audit(make_audit(PASSWORD_RESET, user_id=user.id, ctx=ctx))
            await uow.commit()
