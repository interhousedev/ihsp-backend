"""Ports the MCP interface needs: audit events and the course scope of connectors."""

from uuid import UUID

from app.modules.identity.infrastructure.audit_writer import write_audit_events
from app.modules.identity.infrastructure.repositories.mcp_call_log_repository import (
    SqlMcpCallLogRepository,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.notifications import AuditDraft

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class McpAuditAdapter:
    """McpAuditPort: one `id.audit_events` row per MCP call or denial."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker (each event commits on its own)."""
        self._sessionmaker = sessionmaker

    async def audit(self, event: AuditDraft) -> None:
        """Store one audit event."""
        async with self._sessionmaker() as session, session.begin():
            await write_audit_events(session, [event])


class McpCallLogAdapter:
    """McpCallLog: one `id.mcp_call_log` row per tool call, in its own transaction."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker (a trace never joins the tool's work)."""
        self._sessionmaker = sessionmaker

    async def record(self, entry: McpCallRecord) -> None:
        """Store one trace."""
        async with self._sessionmaker() as session, session.begin():
            await SqlMcpCallLogRepository(session).add(entry)


class ConnectorCoursesAdapter:
    """ConnectorCoursesPort: the courses an LMS connector is limited to."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Keep the identity unit of work factory."""
        self._uow_factory = uow_factory

    async def allowed_course_ids(self, connector_id: UUID) -> frozenset[UUID] | None:
        """Return the connector's courses; None means all of the user's courses."""
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get(connector_id)
        if connector is None:
            return frozenset()  # unknown connector: no course at all
        if connector.course_ids is None:
            return None
        return frozenset(connector.course_ids)
