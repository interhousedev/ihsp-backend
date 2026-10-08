"""GET /v1/id/consent: auto-accept first-party clients, describe MCP clients."""

from dataclasses import dataclass

from app.modules.identity.application.auto_accept_consent import AutoAcceptConsent
from app.modules.identity.application.consent_support import (
    is_dynamic,
    is_verified,
    mcp_server,
    parse_uuid,
    redirect_domain,
    requested_scopes,
)
from app.modules.identity.domain.client_policy import is_first_party
from app.modules.identity.domain.errors import (
    AdminServerForbiddenError,
    RoleMissingError,
    UserNotFoundError,
)
from app.modules.identity.domain.scopes import Server, role_may_use_server
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class ConsentInfo:
    """What the consent screen shows (README MCP-3)."""

    client_id: str
    client_name: str
    verified: bool
    redirect_domain: str
    server: Server | None
    requested_scopes: list[str]
    requires_otp: bool
    redirect_to: str | None


@dataclass(frozen=True, slots=True)
class GetConsentInfo:
    """Load a consent request and decide whether the user must see a screen."""

    uow_factory: UowFactory
    hydra: HydraGateway
    auto_accept: AutoAcceptConsent

    async def execute(self, challenge: str) -> ConsentInfo:
        """Return the screen data, or ``redirect_to`` for first-party clients."""
        request = await self.hydra.get_consent_request(challenge)
        client = request.client
        if is_first_party(client.client_id):
            redirect = await self.auto_accept.execute(request)
            return ConsentInfo(
                client_id=client.client_id,
                client_name=client.client_name,
                verified=True,
                redirect_domain=redirect_domain(request),
                server=None,
                requested_scopes=list(request.requested_scope),
                requires_otp=False,
                redirect_to=redirect,
            )
        server = await self._check_mcp(request)
        return ConsentInfo(
            client_id=client.client_id,
            client_name=client.client_name,
            verified=is_verified(client),
            redirect_domain=redirect_domain(request),
            server=server,
            requested_scopes=requested_scopes(request, server),
            requires_otp=server == "admin",
            redirect_to=None,
        )

    async def _check_mcp(self, request: ConsentRequest) -> Server:
        """Server of the request; refuse roles and clients that may not use it."""
        server = mcp_server(request)
        user_id = parse_uuid(request.subject)
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id) if user_id else None
        if user is None or not user.is_active:
            raise UserNotFoundError(params={"user_id": request.subject})
        if not role_may_use_server(user.roles, server):
            raise RoleMissingError(params={"server": server})
        client = request.client
        if server == "admin" and is_dynamic(client) and not is_verified(client):
            raise AdminServerForbiddenError(params={"client_id": client.client_id})
        return server
