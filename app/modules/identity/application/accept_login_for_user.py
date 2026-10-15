"""LoginAcceptor implementation: log a user in without asking for credentials.

Used by registration and reclaim (B2) right after the account is created, and by
the one-time sign-in ticket of a registration or password reset that had no login
challenge: IHT ID then starts its own login and redeems the ticket there.
"""

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.errors import (
    LoginTicketInvalidError,
    UserNotFoundError,
)
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory

LOGIN_TICKET_KEY = "login-ticket:{ticket}"
LOGIN_TICKET_SECONDS = 600


@dataclass(frozen=True, slots=True)
class LoginAcceptorImpl:
    """Creates the Session and accepts the login challenge."""

    uow_factory: UowFactory
    hydra: HydraGateway
    starter: LoginSessionStarter

    async def accept(
        self,
        challenge: str,
        user_id: UUID,
        *,
        amr: Sequence[str],
        ip: str | None,
        user_agent: str | None,
        remember: bool,
    ) -> str:
        """Return the URL to send the browser to."""
        request = await self.hydra.get_login_request(challenge)
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or not user.is_active:
                raise UserNotFoundError(params={"user_id": str(user_id)})
            return await self.starter.start(
                uow,
                request,
                user,
                amr=amr,
                mfa=False,
                ctx=RequestContext(ip=ip, user_agent=user_agent),
                remember=remember,
            )

    async def issue_ticket(self, user_id: UUID, *, amr: Sequence[str]) -> str:
        """A one-time ticket that signs ``user_id`` in on the next login challenge."""
        ticket = secrets.token_urlsafe(32)
        await self.starter.tickets.put(
            LOGIN_TICKET_KEY.format(ticket=ticket),
            {"user_id": str(user_id), "amr": list(amr)},
            ttl=LOGIN_TICKET_SECONDS,
        )
        return ticket

    async def redeem_ticket(
        self, challenge: str, ticket: str, *, ip: str | None, user_agent: str | None
    ) -> str:
        """Accept ``challenge`` for the ticket's user (remembered device)."""
        key = LOGIN_TICKET_KEY.format(ticket=ticket)
        data = await self.starter.tickets.get(key)
        if data is None:
            raise LoginTicketInvalidError()
        await self.starter.tickets.delete(key)
        return await self.accept(
            challenge,
            UUID(str(data["user_id"])),
            amr=list(data.get("amr") or ["pwd"]),
            ip=ip,
            user_agent=user_agent,
            remember=True,
        )
