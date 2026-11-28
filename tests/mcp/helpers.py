"""Small helpers shared by the MCP tests."""

from typing import Any

from app.interfaces.mcp.catalog import META_TOOLS
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.server import _BUILDERS

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, Tool


async def call(
    session: ClientSession, name: str, /, **arguments: Any
) -> CallToolResult:
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


async def registered_tools(deps: McpDeps, server: str) -> list[Tool]:
    """Every tool registered on `server`, as `tools/list` would show it unfiltered.

    The served `tools/list` is only the meta and pinned tools, so assertions about
    what is registered (names, hints, schemas) read the server object instead. Role
    filtering is not applied here: assert it through `search_tools`/`describe_tool`.
    """
    tools = await FastMCP.list_tools(_BUILDERS[server](deps))
    return [tool for tool in tools if tool.name not in META_TOOLS]
