"""Port: persistence of MCP connectors."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.connector import McpConnector


class ConnectorRepository(Protocol):
    """Reads and writes MCP connectors."""

    async def add(self, connector: McpConnector) -> None:
        """Insert a connector."""
        ...

    async def get(self, connector_id: UUID) -> McpConnector | None:
        """Return the connector or None."""
        ...

    async def get_by_token_hash(self, token_hash: str) -> McpConnector | None:
        """Find a token connector by the hash of its token."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[McpConnector]:
        """Connectors of a user, newest first."""
        ...

    async def save(self, connector: McpConnector) -> None:
        """Write every field of an existing connector."""
        ...

    async def revoke_all_for_user(
        self, user_id: UUID, now: datetime
    ) -> list[McpConnector]:
        """Revoke every active connector of a user and return them."""
        ...

    async def last_used_by_client(
        self, client_ids: Sequence[str]
    ) -> dict[str, datetime | None]:
        """Latest last_used_at per Hydra client id."""
        ...

    async def touch_last_used(
        self, connector_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_used_at unless it was updated within min_interval."""
        ...
