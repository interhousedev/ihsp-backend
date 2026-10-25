"""POST /v1/admin/oauth-clients/{client_id}/verify: mark an MCP client verified."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.list_oauth_clients import (
    OAuthClientView,
    view_of,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import OAUTH_CLIENT_VERIFIED
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError


@dataclass(frozen=True, slots=True)
class VerifyOAuthClient:
    """Stores `verified` in the client's Hydra metadata (MCP-3)."""

    uow_factory: UowFactory
    hydra: HydraGateway

    async def execute(
        self, actor: Actor, client_id: str, *, verified: bool, ctx: RequestContext
    ) -> OAuthClientView:
        """Set the flag and return the updated client."""
        client = await self.hydra.get_client(client_id)
        if client is None:
            raise NotFoundError(params={"client_id": client_id})
        updated = await self.hydra.set_client_metadata(
            client_id, {**client.metadata, "verified": verified}
        )
        async with self.uow_factory() as uow:
            uow.audit(
                make_audit(
                    OAUTH_CLIENT_VERIFIED,
                    user_id=None,
                    ctx=ctx,
                    actor_id=actor.user_id,
                    client_id=client_id,
                    verified=verified,
                )
            )
            used = await uow.connectors.last_used_by_client([client_id])
            await uow.commit()
        return view_of(updated, used.get(client_id))
