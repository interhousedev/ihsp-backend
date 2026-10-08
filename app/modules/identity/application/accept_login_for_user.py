"""LoginAcceptor implementation: log a user in without asking for credentials.

Used by registration and reclaim (B2) right after the account is created.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import LoginSessionStarter
from app.modules.identity.domain.errors import UserNotFoundError
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory


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
