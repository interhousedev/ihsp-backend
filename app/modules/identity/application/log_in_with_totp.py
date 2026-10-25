"""POST /v1/id/login/totp: finish a password login with the authenticator app."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import TotpVerifier, load_factors
from app.modules.identity.application.login_result import LoginResult, SecondFactor
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.audit_event import TOTP_RECOVERY_USED
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import OtpInvalidError, RoleMissingError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway, LoginRequest
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.ids import random_token
from app.shared.rate_limit import RateLimiter

IP_LIMIT_PER_HOUR = 300
TICKET_TTL_SECONDS = 300
MAX_ATTEMPTS = 5


async def issue_totp_ticket(
    tickets: TicketStore, user: User, request: LoginRequest, remember: bool
) -> LoginResult:
    """After the password: the client must send a TOTP code with this ticket."""
    ticket = random_token(16)
    await tickets.put(
        f"login-totp:{ticket}",
        {
            "user_id": str(user.id),
            "challenge": request.challenge,
            "remember": remember,
            "attempts": 0,
        },
        ttl=TICKET_TTL_SECONDS,
    )
    return LoginResult(second_factor=SecondFactor(ticket=ticket, method="totp"))


@dataclass(frozen=True, slots=True)
class LogInWithTotp:
    """A 6-digit code (±1 step, never reused) or a one-time recovery code."""

    uow_factory: UowFactory
    hydra: HydraGateway
    tickets: TicketStore
    verifier: TotpVerifier
    starter: LoginSessionStarter
    rate_limiter: RateLimiter

    async def execute(
        self, challenge: str, ticket: str, code: str, *, ctx: RequestContext
    ) -> LoginResult:
        """Return the redirect URL or raise OtpInvalidError."""
        await self.rate_limiter.hit(
            f"login-totp-ip:{ctx.throttle_ip}",
            limit=IP_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
        key = f"login-totp:{ticket}"
        pending = await self.tickets.get(key)
        if pending is None or pending.get("challenge") != challenge:
            raise OtpInvalidError(params={"attempts_left": 0})
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            user = await uow.users.get(UUID(str(pending["user_id"])))
            if user is None or not user.is_active:
                await self.tickets.delete(key)
                raise OtpInvalidError(params={"attempts_left": 0})
            factors = await load_factors(uow, user.id)
            used = await self.verifier.verify(factors, code)
            if used is None:
                raise await self._failure(key, pending)
            await uow.factors.save(factors)
            if used == "recovery":
                left = len(factors.recovery_code_hashes)
                uow.audit(
                    make_audit(TOTP_RECOVERY_USED, user_id=user.id, ctx=ctx, left=left)
                )
            await self.tickets.delete(key)
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            redirect = await self.starter.start(
                uow,
                request,
                user,
                amr=["pwd", "otp"],
                mfa=True,
                ctx=ctx,
                remember=bool(pending.get("remember")),
            )
        return LoginResult(redirect_to=redirect)

    async def _failure(self, key: str, pending: dict[str, object]) -> OtpInvalidError:
        attempts = int(str(pending.get("attempts") or 0)) + 1
        left = max(MAX_ATTEMPTS - attempts, 0)
        if left == 0:
            await self.tickets.delete(key)
        else:
            await self.tickets.put(
                key, {**pending, "attempts": attempts}, ttl=TICKET_TTL_SECONDS
            )
        return OtpInvalidError(params={"attempts_left": left})
