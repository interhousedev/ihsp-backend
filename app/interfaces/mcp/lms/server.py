"""The LMS Course MCP server: read, and add-only drafting (MCP-1, MCP-6)."""

from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_toolkit
from app.interfaces.mcp.lms.tools import (
    add_flashcards_block,
    add_question,
    add_test_block,
    add_text_block,
    create_section,
    create_step,
    get_course,
    get_step,
    list_attempts,
    list_courses,
    list_pending_changes,
    list_versions,
)

from mcp.server.fastmcp import FastMCP

TOOL_MODULES = (
    list_courses,
    get_course,
    get_step,
    list_pending_changes,
    list_versions,
    list_attempts,
    create_section,
    create_step,
    add_text_block,
    add_test_block,
    add_question,
    add_flashcards_block,
)


def build_lms_server(deps: McpDeps) -> FastMCP:
    """Create the LMS Course server with all its tools registered."""
    kit = make_toolkit(
        deps,
        "lms",
        title="IHSP LMS Course",
        instructions_key="mcp-instructions-lms",
    )
    for module in TOOL_MODULES:
        module.register(kit)
    return kit.mcp
