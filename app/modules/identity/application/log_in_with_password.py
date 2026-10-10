"""POST /v1/id/login: password login; administrators with OTP on enter a code."""

from dataclasses import dataclass

from app.modules.identity.application.login_result import LoginResult, SecondFactor
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.password_authenticator import (
    PasswordAuthenticator,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import RoleMissingError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway, LoginRequest
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.ids import random_token
from app.shared.rate_limit import RateLimiter

IP_LIMIT_PER_HOUR = 300
TICKET_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class LogInWithPassword:
    """Check the password, the status and the role, then accept or ask for a code."""

    uow_factory: UowFactory
    hydra: HydraGateway
    authenticator: PasswordAuthenticator
    rate_limiter: RateLimiter
    tickets: TicketStore
    otp: OtpService
    starter: LoginSessionStarter

    async def execute(
        self,
        challenge: str,
        login: str,
        password: str,
        *,
        remember: bool,
        ctx: RequestContext,
    ) -> LoginResult:
        """Return the redirect URL, or a second-factor ticket (OTP on)."""
        await self.rate_limiter.hit(
            f"login-ip:{ctx.throttle_ip}", limit=IP_LIMIT_PER_HOUR, window_seconds=3600
        )
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            user = await self.authenticator.authenticate(uow, login, password, ctx)
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            if user.is_admin and user.otp_enabled:
                return await self._second_factor(uow, user, request, remember, ctx)
            redirect = await self.starter.start(
                uow, request, user, amr=["pwd"], mfa=False, ctx=ctx, remember=remember
            )
        return LoginResult(redirect_to=redirect)

    async def _second_factor(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        request: LoginRequest,
        remember: bool,
        ctx: RequestContext,
    ) -> LoginResult:
        ticket = random_token(16)
        links = await uow.telegram_links.list_for_user(user.id)
        channels = await self.otp.send(
            user, links, purpose="login2fa", subject_key=ticket, ctx=ctx
        )
        await self.tickets.put(
            f"login2fa:{ticket}",
            {
                "user_id": str(user.id),
                "challenge": request.challenge,
                "remember": remember,
            },
            ttl=TICKET_TTL_SECONDS,
        )
        return LoginResult(second_factor=SecondFactor(ticket=ticket, channels=channels))
