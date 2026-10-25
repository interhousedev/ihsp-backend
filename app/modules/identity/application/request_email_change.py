"""POST /v1/id/me/email/change: password, then a code to the new address (ID-25)."""

from dataclasses import dataclass

from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import EmailTakenError, InvalidCredentialsError
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter

PENDING_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class RequestEmailChange:
    """Verifies the password and sends a code to the new address."""

    uow_factory: UowFactory
    hasher: PasswordHasher
    otp: OtpService
    tickets: TicketStore
    rate_limiter: RateLimiter

    async def execute(
        self, actor: Actor, password: str, new_email: str, ctx: RequestContext
    ) -> None:
        """Start the change; the code goes to ``new_email`` only."""
        await self.rate_limiter.hit(
            f"email-change:{actor.user_id}", limit=5, window_seconds=3600
        )
        email = new_email.strip().lower()
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not await self.hasher.verify(user.password_hash, password):
                raise InvalidCredentialsError()
            if await uow.users.email_taken(email, except_user_id=user.id):
                raise EmailTakenError()
            locale = user.locale
        await self.tickets.put(
            f"email-change:{actor.user_id}", {"email": email}, ttl=PENDING_TTL_SECONDS
        )
        await self.otp.send_to_email(
            email,
            purpose="email-change",
            subject_key=str(actor.user_id),
            locale=locale,
        )
