"""Small helpers shared by the MCP tests."""

from typing import Any

from mcp.client.session import ClientSession
from mcp.types import CallToolResult, TextContent


async def call(session: ClientSession, name: str, **arguments: Any) -> CallToolResult:
    """Call a tool and return the raw result."""
    return await session.call_tool(name, arguments)


def text_of(result: CallToolResult) -> str:
    """Join the text content of a result."""
    return "\n".join(c.text for c in result.content if isinstance(c, TextContent))


def data_of(result: CallToolResult) -> dict[str, Any]:
    """Return the structured content of a successful result."""
    assert not result.isError, text_of(result)
    assert result.structuredContent is not None
    return result.structuredContent


async def tool_names(session: ClientSession) -> set[str]:
    """Names of all tools a server offers."""
    listed = await session.list_tools()
    return {tool.name for tool in listed.tools}
