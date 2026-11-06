"""Port: persistence of the MCP call log."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.shared.contracts.mcp_calls import McpCallOutcome, McpCallRecord
from app.shared.pagination import Page


@dataclass(frozen=True, slots=True)
class McpCallEntry:
    """A stored trace."""

    id: UUID
    created_at: datetime
    user_id: UUID
    connector_id: UUID | None
    connector_name: str | None
    client_id: str | None
    server: str
    tool: str
    scope: str
    read_only: bool
    outcome: McpCallOutcome
    error_code: str | None
    error_id: str | None
    duration_ms: int
    arguments: dict[str, Any] | None
    result_summary: dict[str, Any] | None
    ip: str | None


@dataclass(frozen=True, slots=True)
class McpCallFilter:
    """What to read; a None field does not filter."""

    user_id: UUID | None = None
    connector_id: UUID | None = None
    server: str | None = None
    tool: str | None = None
    outcome: str | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class McpToolSummary:
    """Calls of one tool; `errors` counts every outcome other than ok."""

    server: str
    tool: str
    calls: int
    errors: int


class McpCallLogRepository(Protocol):
    """Writes, reads and purges call traces."""

    async def add(self, entry: McpCallRecord) -> None:
        """Insert one trace, copying the current name of its connector."""
        ...

    async def search(
        self, where: McpCallFilter, *, cursor: str | None, limit: int
    ) -> Page[McpCallEntry]:
        """Newest first with a (created_at, id) cursor."""
        ...

    async def summary(self, where: McpCallFilter) -> list[McpToolSummary]:
        """Calls and failures per server and tool, busiest first."""
        ...

    async def purge_before(self, cutoff: datetime, *, limit: int) -> int:
        """Delete up to `limit` rows older than the cutoff; return how many."""
        ...
