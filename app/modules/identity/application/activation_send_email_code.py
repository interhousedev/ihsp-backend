"""POST /v1/id/activation/{token}/email: send the code that proves the address."""

from dataclasses import dataclass

from app.modules.identity.application.activation_token import user_for_token
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import EmailTakenError
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import hash_token
from app.shared.rate_limit import RateLimiter

PENDING_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class ActivationSendEmailCode:
    """Step 3 of UF-ID-13: confirm the recovery email with a code."""

    uow_factory: UowFactory
    otp: OtpService
    tickets: TicketStore
    rate_limiter: RateLimiter
    clock: Clock

    async def execute(self, token: str, email: str, ctx: RequestContext) -> None:
        """Send the code to ``email`` (not to the address stored earlier)."""
        key = hash_token(token)
        await self.rate_limiter.hit(f"activation:{key}", limit=5, window_seconds=3600)
        address = email.strip().lower()
        async with self.uow_factory() as uow:
            user = await user_for_token(uow, token, self.clock)
            if await uow.users.email_taken(address, except_user_id=user.id):
                raise EmailTakenError()
            locale = user.locale
        await self.tickets.put(
            f"activation-email:{key}", {"email": address}, ttl=PENDING_TTL_SECONDS
        )
        await self.otp.send_to_email(
            address, purpose="activation-email", subject_key=key, locale=locale
        )
