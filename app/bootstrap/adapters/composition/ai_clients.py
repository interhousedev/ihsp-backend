"""Composition port: connected AI clients and the AI access Administration set."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.connector_status import ConnectorStatus
from app.shared.limits import LimitsProvider


@dataclass(frozen=True, slots=True)
class AiClientViewsAdapter:
    """Reads the MCP connectors and the revoked AI scopes; changes nothing."""

    connectors: ConnectorStatus
    limits: LimitsProvider

    async def has_connected_client(self, user_id: UUID) -> bool:
        """True when an MCP connector of the user is not revoked."""
        return await self.connectors.has_active(user_id)

    async def chat_blocked(self, user_id: UUID) -> bool:
        """True when Administration revoked the chat AI from the user."""
        return (await self.limits.ai_access(user_id)).blocks("chat")
