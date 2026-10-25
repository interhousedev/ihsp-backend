"""DELETE /v1/id/me/connectors/{id}: revoke a connector; it stops working at once."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import CONNECTOR_REVOKED
from app.modules.identity.domain.errors import HydraUnavailableError
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.revocation_list import RevocationList
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RevokeConnector:
    """Marks the connector revoked and cuts its OAuth tokens (MCP-4)."""

    uow_factory: UowFactory
    hydra: HydraGateway
    revocations: RevocationList
    clock: Clock

    async def execute(
        self, actor: Actor, connector_id: UUID, ctx: RequestContext
    ) -> None:
        """Revoke one of the caller's connectors."""
        async with self.uow_factory() as uow:
            connector = await uow.connectors.get(connector_id)
            if connector is None or connector.user_id != actor.user_id:
                raise NotFoundError(params={"connector_id": str(connector_id)})
            if connector.revoked_at is not None:
                return
            connector.revoked_at = self.clock.now()
            await uow.connectors.save(connector)
            uow.audit(
                make_audit(
                    CONNECTOR_REVOKED,
                    user_id=actor.user_id,
                    ctx=ctx,
                    connector_id=str(connector.id),
                    server=connector.server,
                )
            )
            await uow.commit()
        await self.revocations.revoke(connector.id)
        if connector.hydra_client_id:
            await self._cut_oauth_tokens(actor.user_id, connector.hydra_client_id)

    async def _cut_oauth_tokens(self, user_id: UUID, client_id: str) -> None:
        # The token hook already refuses refreshes of a revoked connector.
        try:
            await self.hydra.revoke_consent_sessions(str(user_id), client_id)
        except HydraUnavailableError:
            log.warning("hydra_revoke_failed", client_id=client_id)
