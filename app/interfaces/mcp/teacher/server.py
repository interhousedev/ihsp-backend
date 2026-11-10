"""The Teachers MCP server: the teacher's own lessons, groups and controls."""

from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_toolkit
from app.interfaces.mcp.teacher import ai_tools
from app.interfaces.mcp.teacher.tools import (
    assessments_read,
    assessments_write,
    groups,
    homework,
    journal,
    marks_read,
    marks_write,
    schedule,
    workoffs,
)
from app.shared.brand import current_brand

from mcp.server.fastmcp import FastMCP

TOOL_MODULES = (
    schedule,
    groups,
    journal,
    homework,
    marks_read,
    marks_write,
    assessments_read,
    assessments_write,
    workoffs,
)


def build_teacher_server(deps: McpDeps) -> FastMCP:
    """Create the Teachers server with all its tools registered."""
    kit = make_toolkit(
        deps,
        "teacher",
        title=f"{current_brand().name} Teachers",
        instructions_key="mcp-instructions-teacher",
    )
    for module in TOOL_MODULES:
        module.register(kit)
    ai_tools.register(kit)
    return kit.mcp
