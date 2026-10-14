"""POST /v1/id/login/otp: finish a login with a one-time code."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.passwordless_otp_check import PasswordlessOtpCheck
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.restore_account import RestoreOffer
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import OtpInvalidError, RoleMissingError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.rate_limit import RateLimiter

IP_LIMIT_PER_HOUR = 300


@dataclass(frozen=True, slots=True)
class LogInWithOtp:
    """With a ticket: the second factor after the password. Without: passwordless."""

    uow_factory: UowFactory
    hydra: HydraGateway
    otp: OtpService
    passwordless: PasswordlessOtpCheck
    tickets: TicketStore
    starter: LoginSessionStarter
    rate_limiter: RateLimiter
    restore_offer: RestoreOffer | None = None

    async def execute(
        self,
        challenge: str,
        login: str,
        code: str,
        *,
        ticket: str | None,
        ctx: RequestContext,
    ) -> LoginResult:
        """Return the redirect URL or raise OtpInvalidError / RateLimitedError."""
        await self.rate_limiter.hit(
            f"login-otp-ip:{ctx.throttle_ip}",
            limit=IP_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            if ticket:
                user, amr, mfa, remember = await self._second_factor(
                    uow, challenge, login, code, ticket, ctx
                )
            else:
                user = await self.passwordless.execute(
                    uow,
                    login,
                    code,
                    ctx,
                    allow_pending_deletion=self.restore_offer is not None,
                )
                amr, mfa, remember = ["otp"], False, False
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            if self.restore_offer is not None and user.is_pending_deletion:
                return await self.restore_offer.make(
                    user, request.challenge, amr=amr, remember=remember
                )
            redirect = await self.starter.start(
                uow, request, user, amr=amr, mfa=mfa, ctx=ctx, remember=remember
            )
        return LoginResult(redirect_to=redirect)

    async def _second_factor(
        self,
        uow: IdentityUnitOfWorkPort,
        challenge: str,
        login: str,
        code: str,
        ticket: str,
        ctx: RequestContext,
    ) -> tuple[User, list[str], bool, bool]:
        # Every failure answers alike, so the ticket's liveness is not revealed.
        pending: dict[str, Any] | None = await self.tickets.get(f"login2fa:{ticket}")
        if pending is None or pending.get("challenge") != challenge:
            raise await self.passwordless.failure("login2fa", login, ctx.throttle_ip)
        try:
            await self.otp.check("login2fa", ticket, code)
        except OtpInvalidError:
            raise await self.passwordless.failure(
                "login2fa", login, ctx.throttle_ip
            ) from None
        await self.tickets.delete(f"login2fa:{ticket}")
        user = await uow.users.get(UUID(pending["user_id"]))
        if user is None or not user.is_active:
            raise await self.passwordless.failure("login2fa", login, ctx.throttle_ip)
        if (user.login or "").lower() != login.strip().lower():
            raise await self.passwordless.failure("login2fa", login, ctx.throttle_ip)
        await self.passwordless.throttle.reset_code_failures(
            "login2fa", login, ctx.throttle_ip
        )
        return user, ["pwd", "otp"], True, bool(pending.get("remember"))
