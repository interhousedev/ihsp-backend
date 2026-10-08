"""POST /v1/id/me/otp/disable: turn OTP login off (not for Administration)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OTP_DISABLED
from app.modules.identity.domain.errors import (
    InvalidCredentialsError,
    OtpMandatoryError,
)
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter


@dataclass(frozen=True, slots=True)
class DisableOtp:
    """Needs the password; Administration cannot switch OTP off (ID-11)."""

    uow_factory: UowFactory
    hasher: PasswordHasher
    rate_limiter: RateLimiter

    async def execute(self, actor: Actor, password: str, ctx: RequestContext) -> None:
        """Disable OTP login or raise."""
        await self.rate_limiter.hit(
            f"otp-disable:{actor.user_id}", limit=5, window_seconds=3600
        )
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if user.is_admin:
                raise OtpMandatoryError()
            if not await self.hasher.verify(user.password_hash, password):
                raise InvalidCredentialsError()
            user.otp_enabled = False
            user.otp_via_email = False
            await uow.users.save(user)
            uow.audit(make_audit(OTP_DISABLED, user_id=user.id, ctx=ctx))
            await uow.commit()
