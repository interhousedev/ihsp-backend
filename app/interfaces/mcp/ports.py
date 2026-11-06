"""Small ports the MCP interface needs that no contract provides (I1 implements)."""

from typing import Protocol
from uuid import UUID

from app.shared.contracts.files import FileRef, FilesApi
from app.shared.notifications import AuditDraft


class McpAuditPort(Protocol):
    """Writes MCP audit events (`mcp.call`, `mcp.denied`) outside any use case."""

    async def audit(self, event: AuditDraft) -> None:
        """Store one audit event."""
        ...


class ConnectorCoursesPort(Protocol):
    """Reads the course restriction of an LMS connector."""

    async def allowed_course_ids(self, connector_id: UUID) -> frozenset[UUID] | None:
        """Return the courses the connector is limited to; None means all."""
        ...


class McpScopeOverlayPort(Protocol):
    """Scopes added to a connector after its OAuth token was issued (A7)."""

    async def extra_scopes(self, connector_id: UUID) -> frozenset[str]:
        """The extra scopes of a connector; the adapter caches them for 30 seconds."""
        ...


class McpFilesApi(FilesApi, Protocol):
    """FilesApi plus the listing of a user's own files (missing from the contract)."""

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """Return the owner's ready files, newest first."""
        ...
