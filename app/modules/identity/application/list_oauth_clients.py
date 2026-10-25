"""GET /v1/admin/oauth-clients: MCP clients that registered themselves."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.application.consent_support import is_dynamic, is_verified
from app.modules.identity.domain.client_policy import MINIAPP_CLIENT, is_first_party
from app.modules.identity.ports.hydra_gateway import HydraClient, HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class OAuthClientView:
    """One client for the admin screen."""

    client_id: str
    name: str
    verified: bool
    dynamic: bool
    last_used_at: datetime | None


def view_of(client: HydraClient, last_used: datetime | None) -> OAuthClientView:
    """Build the admin view of a Hydra client."""
    return OAuthClientView(
        client_id=client.client_id,
        name=client.client_name,
        verified=is_verified(client),
        dynamic=is_dynamic(client),
        last_used_at=last_used,
    )


@dataclass(frozen=True, slots=True)
class ListOAuthClients:
    """Lists the non first-party clients with their last use."""

    uow_factory: UowFactory
    hydra: HydraGateway

    async def execute(self) -> list[OAuthClientView]:
        """Clients known to Hydra, minus our own platforms."""
        clients = [
            c
            for c in await self.hydra.list_clients()
            if not is_first_party(c.client_id) and c.client_id != MINIAPP_CLIENT
        ]
        async with self.uow_factory() as uow:
            used = await uow.connectors.last_used_by_client(
                [c.client_id for c in clients]
            )
        return [view_of(c, used.get(c.client_id)) for c in clients]
