"""Email ownership check by a one-time code (ID-4)."""

from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmailInUseError,
    OtpCodeInvalidError,
)
from app.modules.identity.application.register_ports import (
    EmailSenderPort,
    OtpPort,
    UnitOfWorkFactory,
)
from app.shared.ids import hash_token
from app.shared.rate_limit import RateLimiter

OTP_PURPOSE = "verify_email"
CODE_TTL_MINUTES = 5
COOLDOWN_SECONDS = 60
CODES_PER_FLOW = 5  # a flow lives 30 minutes
CODES_PER_ADDRESS = 5  # per hour, so nobody can flood a stranger's inbox


class EmailVerifier:
    """Sends a code to an email and checks it, keyed by the flow's token."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        otp: OtpPort,
        email_sender: EmailSenderPort,
        rate_limiter: RateLimiter,
    ) -> None:
        """Store the collaborators."""
        self._uow_factory = uow_factory
        self._otp = otp
        self._email_sender = email_sender
        self._rate_limiter = rate_limiter

    async def send(
        self, *, token: str, email: str, except_user_id: UUID | None, locale: str
    ) -> str:
        """Send a new code; return the normalized (stripped, lowercase) email."""
        address = email.strip().lower()
        key = hash_token(token)
        await self._rate_limiter.hit(
            f"reg-email-cooldown:{key}", limit=1, window_seconds=COOLDOWN_SECONDS
        )
        await self._rate_limiter.hit(
            f"reg-email:{key}", limit=CODES_PER_FLOW, window_seconds=1800
        )
        await self._rate_limiter.hit(
            f"reg-email-to:{address}", limit=CODES_PER_ADDRESS, window_seconds=3600
        )
        async with self._uow_factory() as uow:
            if await uow.accounts.email_in_use(address, except_user_id=except_user_id):
                raise EmailInUseError(support_details="email belongs to another user")
        code = await self._otp.issue(OTP_PURPOSE, key)
        await self._email_sender.send(
            address,
            "otp",
            {"code": code, "purpose": OTP_PURPOSE, "ttl_minutes": CODE_TTL_MINUTES},
            locale,
        )
        return address

    async def check(self, token: str, code: str) -> None:
        """Consume the code or raise OtpCodeInvalidError (3 attempts, 5 minutes)."""
        if not await self._otp.verify(OTP_PURPOSE, hash_token(token), code.strip()):
            raise OtpCodeInvalidError()
