"""POST /v1/id/login/restore and /login/restore/decline: a pending deletion.

A password or code login of an account scheduled for deletion does not sign in;
it returns a ticket (bound to the login challenge) and the purge date. Restoring
cancels the deletion and finishes the login; declining rejects the challenge.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.deletion_notice import deletion_date
from app.modules.identity.application.login_result import AccountRestore, LoginResult
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import InvalidCredentialsError, RoleMissingError
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import random_token

TICKET_TTL_SECONDS = 600
ACCOUNT_RESTORED = "account.restored"


def _key(ticket: str) -> str:
    return f"login-restore:{ticket}"


@dataclass(frozen=True, slots=True)
class RestoreOffer:
    """Builds the restore answer of a login whose account is pending deletion."""

    tickets: TicketStore
    clock: Clock
    retention_days: int

    async def make(
        self, user: User, challenge: str, *, amr: list[str], remember: bool
    ) -> LoginResult:
        """Store a ticket for this challenge; return it with the purge date."""
        ticket = random_token(16)
        await self.tickets.put(
            _key(ticket),
            {
                "user_id": str(user.id),
                "challenge": challenge,
                "amr": amr,
                "remember": remember,
            },
            ttl=TICKET_TTL_SECONDS,
        )
        requested = user.deletion_requested_at or self.clock.now()
        return LoginResult(
            restore=AccountRestore(
                ticket=ticket, deletes_on=deletion_date(requested, self.retention_days)
            )
        )


async def _take(tickets: TicketStore, challenge: str, ticket: str) -> dict[str, Any]:
    pending: dict[str, Any] | None = await tickets.get(_key(ticket))
    if pending is None or pending.get("challenge") != challenge:
        raise InvalidCredentialsError()
    return pending


@dataclass(frozen=True, slots=True)
class RestoreAccountAtLogin:
    """Cancel the deletion, then finish the login the ticket belongs to."""

    uow_factory: UowFactory
    hydra: HydraGateway
    tickets: TicketStore
    starter: LoginSessionStarter

    async def execute(
        self, challenge: str, ticket: str, *, ctx: RequestContext
    ) -> LoginResult:
        """Return the redirect URL or raise InvalidCredentialsError."""
        pending = await _take(self.tickets, challenge, ticket)
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            user = await uow.users.get(UUID(pending["user_id"]))
            if user is None or not user.is_pending_deletion:
                raise InvalidCredentialsError()
            if not may_use_client(request.client.client_id, user.roles):
                raise RoleMissingError(params={"client_id": request.client.client_id})
            await self.tickets.delete(_key(ticket))
            user.restore()
            await uow.users.save(user)
            uow.audit(make_audit(ACCOUNT_RESTORED, user_id=user.id, ctx=ctx))
            redirect = await self.starter.start(
                uow,
                request,
                user,
                amr=list(pending.get("amr") or ["pwd"]),
                mfa=False,
                ctx=ctx,
                remember=bool(pending.get("remember")),
            )
        return LoginResult(redirect_to=redirect)


@dataclass(frozen=True, slots=True)
class DeclineAccountRestore:
    """Keep the deletion: drop the ticket and reject the login challenge."""

    hydra: HydraGateway
    tickets: TicketStore

    async def execute(self, challenge: str, ticket: str) -> str:
        """Return where Hydra sends the browser next."""
        await _take(self.tickets, challenge, ticket)
        await self.tickets.delete(_key(ticket))
        return await self.hydra.reject_login(
            challenge, "access_denied", "The account is scheduled for deletion."
        )
