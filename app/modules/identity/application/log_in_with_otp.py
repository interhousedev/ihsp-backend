"""POST /v1/id/login/otp: finish a login with a one-time code."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.passwordless_otp_check import PasswordlessOtpCheck
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import OtpInvalidError, RoleMissingError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory


@dataclass(frozen=True, slots=True)
class LogInWithOtp:
    """With a ticket: the second factor after the password. Without: passwordless."""

    uow_factory: UowFactory
    hydra: HydraGateway
    otp: OtpService
    passwordless: PasswordlessOtpCheck
    tickets: TicketStore
    starter: LoginSessionStarter

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
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            if ticket:
                user, amr, mfa, remember = await self._second_factor(
                    uow, challenge, login, code, ticket
                )
            else:
                user = await self.passwordless.execute(uow, login, code, ctx)
                amr, mfa, remember = ["otp"], False, False
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
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
    ) -> tuple[User, list[str], bool, bool]:
        pending: dict[str, Any] | None = await self.tickets.get(f"login2fa:{ticket}")
        if pending is None or pending.get("challenge") != challenge:
            raise OtpInvalidError(params={"attempts_left": 0})
        await self.otp.check("login2fa", ticket, code)
        await self.tickets.delete(f"login2fa:{ticket}")
        user = await uow.users.get(UUID(pending["user_id"]))
        if user is None or not user.is_active:
            raise OtpInvalidError(params={"attempts_left": 0})
        if (user.login or "").lower() != login.strip().lower():
            raise OtpInvalidError(params={"attempts_left": 0})
        return user, ["pwd", "otp"], True, bool(pending.get("remember"))
