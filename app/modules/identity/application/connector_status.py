"""Whether a user has an AI client connected (an MCP connector not revoked)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class ConnectorStatus:
    """Read-only check used by the dashboard; creates and changes nothing."""

    uow_factory: UowFactory

    async def has_active(self, user_id: UUID) -> bool:
        """True when at least one connector of the user is not revoked."""
        async with self.uow_factory() as uow:
            connectors = await uow.connectors.list_for_user(user_id)
        return any(connector.revoked_at is None for connector in connectors)
