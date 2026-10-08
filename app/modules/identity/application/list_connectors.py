"""GET /v1/id/me/connectors: the caller's MCP connectors."""

from dataclasses import dataclass

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class ListConnectors:
    """Lists connectors, newest first (MCP-4)."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor) -> list[McpConnector]:
        """Return every connector of the caller, revoked ones included."""
        async with self.uow_factory() as uow:
            return await uow.connectors.list_for_user(actor.user_id)
