"""One row of the MCP call log (B1); identity stores it, the MCP guard writes it."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

McpCallOutcome = Literal[
    "ok", "denied", "rate_limited", "not_found", "invalid", "error"
]


@dataclass(frozen=True, slots=True)
class McpCallRecord:
    """A trace of a tool call, redacted by `app/interfaces/mcp/call_log.py`."""

    user_id: UUID
    connector_id: UUID | None
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


class McpCallLog(Protocol):
    """Stores call traces, each in its own short transaction."""

    async def record(self, entry: McpCallRecord) -> None:
        """Store one trace."""
        ...
