"""SQLAlchemy repository of MCP connectors (id.mcp_connectors)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.infrastructure.orm import McpConnector as ConnectorRow

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: ConnectorRow) -> McpConnector:
    return McpConnector(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        server=row.server,
        scopes=list(row.scopes or []),
        course_ids=list(row.course_ids) if row.course_ids is not None else None,
        token_hash=row.token_hash,
        token_prefix=row.token_prefix,
        hydra_client_id=row.hydra_client_id,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


def _apply(row: ConnectorRow, connector: McpConnector) -> None:
    row.user_id = connector.user_id
    row.name = connector.name
    row.server = connector.server
    row.scopes = list(connector.scopes)
    row.course_ids = connector.course_ids
    row.token_hash = connector.token_hash
    row.token_prefix = connector.token_prefix
    row.hydra_client_id = connector.hydra_client_id
    row.expires_at = connector.expires_at
    row.last_used_at = connector.last_used_at
    row.revoked_at = connector.revoked_at


class SqlConnectorRepository:
    """ConnectorRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def add(self, connector: McpConnector) -> None:
        """Insert a connector."""
        row = ConnectorRow(id=connector.id)
        _apply(row, connector)
        self._session.add(row)
        await self._session.flush()

    async def get(self, connector_id: UUID) -> McpConnector | None:
        """Return the connector or None."""
        row = await self._session.get(ConnectorRow, connector_id)
        return _to_entity(row) if row else None

    async def get_by_token_hash(self, token_hash: str) -> McpConnector | None:
        """Find a token connector by the hash of its token."""
        row = await self._session.scalar(
            select(ConnectorRow).where(ConnectorRow.token_hash == token_hash)
        )
        return _to_entity(row) if row else None

    async def list_for_user(self, user_id: UUID) -> list[McpConnector]:
        """Connectors of a user, newest first."""
        rows = await self._session.scalars(
            select(ConnectorRow)
            .where(ConnectorRow.user_id == user_id)
            .order_by(ConnectorRow.id.desc())
        )
        return [_to_entity(row) for row in rows]

    async def save(self, connector: McpConnector) -> None:
        """Write every field of an existing connector."""
        row = await self._session.get(ConnectorRow, connector.id)
        if row is None:
            raise LookupError(f"connector {connector.id} does not exist")
        _apply(row, connector)
        await self._session.flush()

    async def revoke_all_for_user(
        self, user_id: UUID, now: datetime
    ) -> list[McpConnector]:
        """Revoke every active connector of a user and return them."""
        rows = await self._session.scalars(
            update(ConnectorRow)
            .where(ConnectorRow.user_id == user_id, ConnectorRow.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(ConnectorRow)
            .execution_options(populate_existing=True)
        )
        return [_to_entity(row) for row in rows]

    async def last_used_by_client(
        self, client_ids: Sequence[str]
    ) -> dict[str, datetime | None]:
        """Latest last_used_at per Hydra client id."""
        if not client_ids:
            return {}
        rows = await self._session.execute(
            select(ConnectorRow.hydra_client_id, func.max(ConnectorRow.last_used_at))
            .where(ConnectorRow.hydra_client_id.in_(list(client_ids)))
            .group_by(ConnectorRow.hydra_client_id)
        )
        found = dict(rows.tuples().all())
        return {client_id: found.get(client_id) for client_id in client_ids}

    async def touch_last_used(
        self, connector_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_used_at unless it was updated within min_interval."""
        await self._session.execute(
            update(ConnectorRow)
            .where(
                ConnectorRow.id == connector_id,
                or_(
                    ConnectorRow.last_used_at.is_(None),
                    ConnectorRow.last_used_at < now - min_interval,
                ),
            )
            .values(last_used_at=now)
        )
