"""What every MCP tool tells a client: description, hints, parameters."""

from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.server import _BUILDERS
from tests.mcp.conftest import World

import pytest
from mcp.server.fastmcp import FastMCP

CREATE_TOOLS = {
    "student": {"create_flashcard_set", "create_test", "create_notebook"},
    "lms": {"create_course", "create_module", "create_section", "create_step"},
}


@pytest.mark.parametrize("server", sorted(_BUILDERS))
async def test_every_tool_describes_itself(world: World, server: str) -> None:
    """Each tool has a text, all four hints and a valid object schema."""
    deps: McpDeps = world.deps()
    # The unfiltered list: the app server's own `list_tools` needs a caller.
    tools = await FastMCP.list_tools(_BUILDERS[server](deps))

    assert tools
    assert len({tool.name for tool in tools}) == len(tools)
    for tool in tools:
        assert tool.description and tool.description.strip(), tool.name
        hints = tool.annotations
        assert hints is not None, tool.name
        assert hints.readOnlyHint is not None, tool.name
        assert hints.destructiveHint is not None, tool.name
        assert hints.idempotentHint is not None, tool.name
        assert hints.openWorldHint is False, tool.name
        assert tool.inputSchema["type"] == "object", tool.name
        if hints.readOnlyHint:
            assert not hints.destructiveHint, tool.name
        assert "ctx" not in tool.inputSchema.get("properties", {}), tool.name


@pytest.mark.parametrize("server", sorted(CREATE_TOOLS))
async def test_create_tools_offer_an_optional_key(world: World, server: str) -> None:
    """The key is advertised and never required."""
    tools = await _BUILDERS[server](world.deps()).list_tools()
    by_name = {tool.name: tool for tool in tools}

    for name in CREATE_TOOLS[server]:
        schema = by_name[name].inputSchema
        assert "idempotency_key" in schema["properties"], name
        assert "idempotency_key" not in schema.get("required", []), name
