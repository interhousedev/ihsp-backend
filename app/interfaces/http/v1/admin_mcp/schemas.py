"""Schemas of the administrators' MCP activity pages."""

from uuid import UUID

from app.interfaces.http.v1.id.connectors.schemas import McpActivityItem
from app.modules.identity.ports.mcp_call_log import McpCallEntry

from pydantic import BaseModel


class AdminMcpActivityItem(McpActivityItem):
    """A call with the person it belongs to."""

    user_id: UUID

    @classmethod
    def of(cls, entry: McpCallEntry) -> "AdminMcpActivityItem":
        """Map a stored trace."""
        return cls(**McpActivityItem.of(entry).model_dump(), user_id=entry.user_id)


class AdminMcpActivityPage(BaseModel):
    """A page of anyone's calls."""

    items: list[AdminMcpActivityItem]
    next_cursor: str | None


class McpToolSummaryItem(BaseModel):
    """Calls of one tool; `errors` counts every outcome other than ok."""

    server: str
    tool: str
    calls: int
    errors: int


class McpActivitySummary(BaseModel):
    """Calls and errors per tool, busiest first."""

    items: list[McpToolSummaryItem]
