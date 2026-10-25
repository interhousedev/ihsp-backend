"""POST /v1/id/login/password: replace an administrator-set password and sign in."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.audit_event import PASSWORD_CHANGED
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import (
    InvalidCredentialsError,
    PasswordPolicyError,
    RoleMissingError,
)
from app.modules.identity.domain.password_policy import check_password
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class LogInWithNewPassword:
    """The step after a password login whose password an administrator set."""

    uow_factory: UowFactory
    hydra: HydraGateway
    hasher: PasswordHasher
    tickets: TicketStore
    starter: LoginSessionStarter

    async def execute(
        self, challenge: str, ticket: str, new_password: str, *, ctx: RequestContext
    ) -> LoginResult:
        """Check the ticket and the new password, store it, then finish the login."""
        key = f"login-pwchange:{ticket}"
        pending: dict[str, Any] | None = await self.tickets.get(key)
        if pending is None or pending.get("challenge") != challenge:
            raise InvalidCredentialsError()
        errors = check_password(new_password)
        if errors:
            raise PasswordPolicyError(params={"errors": errors})
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            user = await uow.users.get(UUID(pending["user_id"]))
            if user is None or not user.is_active:
                raise InvalidCredentialsError()
            if await self.hasher.verify(user.password_hash, new_password):
                raise PasswordPolicyError(params={"errors": ["id-password-unchanged"]})
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            await self.tickets.delete(key)
            user.password_hash = await self.hasher.hash(new_password)
            user.password_change_required = False
            await uow.users.save(user)
            uow.audit(make_audit(PASSWORD_CHANGED, user_id=user.id, ctx=ctx))
            redirect = await self.starter.start(
                uow,
                request,
                user,
                amr=["pwd"],
                mfa=False,
                ctx=ctx,
                remember=bool(pending.get("remember")),
            )
        return LoginResult(redirect_to=redirect)
