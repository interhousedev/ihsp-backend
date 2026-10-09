"""GET /v1/id/login: describe the login request, or skip it (single sign-on)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.start_login_session import REMEMBER_FOR_SECONDS
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.ports.hydra_gateway import HydraGateway, LoginRequest
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class LoginInfo:
    """What the login page needs to know about the request."""

    client_id: str
    client_name: str
    skip: bool
    requires_second_factor: bool
    redirect_to: str | None


@dataclass(frozen=True, slots=True)
class GetLoginInfo:
    """Accept silently when Hydra has a session that is still good enough."""

    uow_factory: UowFactory
    hydra: HydraGateway
    clock: Clock

    async def execute(self, challenge: str) -> LoginInfo:
        """Return the login info; ``redirect_to`` is set when the login was skipped."""
        request = await self.hydra.get_login_request(challenge)
        return await self.describe(request)

    async def describe(self, request: LoginRequest) -> LoginInfo:
        """Describe an already loaded request; accepts it when it can be skipped."""
        client_id = request.client.client_id
        redirect = await self._try_skip(request)
        return LoginInfo(
            client_id=client_id,
            client_name=request.client.client_name,
            skip=redirect is not None,
            requires_second_factor=False,
            redirect_to=redirect,
        )

    async def _try_skip(self, request: LoginRequest) -> str | None:
        if not request.skip or not request.subject:
            return None
        async with self.uow_factory() as uow:
            session = await self._usable_session(uow, request)
        if session is None:
            return None
        return await self.hydra.accept_login(
            request.challenge,
            subject=request.subject,
            remember=True,
            remember_for=REMEMBER_FOR_SECONDS,
            amr=list(session.amr),
            context={
                "session_id": str(session.id),
                "amr": list(session.amr),
                "mfa_at": session.mfa_at.isoformat() if session.mfa_at else None,
            },
        )

    async def _usable_session(
        self, uow: IdentityUnitOfWorkPort, request: LoginRequest
    ) -> LoginSession | None:
        now = self.clock.now()
        try:
            user_id = UUID(request.subject or "")
        except ValueError:
            return None
        user = await uow.users.get(user_id)
        client_id = request.client.client_id
        if (
            user is None
            or not user.is_active
            or not may_use_client(client_id, user.roles)
        ):
            return None
        session = None
        if request.session_id:
            session = await uow.sessions.get_by_hydra_sid(request.session_id)
        if session is None or session.user_id != user_id:
            # No exact match: any live session of the user proves they signed in.
            session = await uow.sessions.latest_active(user_id, now)
        if session is None or session.user_id != user_id or not session.is_active(now):
            return None
        return session
