"""The Administration MCP server: read-only, every call audited (MCP-1)."""

from app.interfaces.mcp.admin.tools import (
    attendance_stats,
    audit_log,
    get_group,
    get_student,
    get_timetable,
    list_broadcasts,
    list_groups,
    list_lessons,
    list_teachers,
    missing_attendance,
    search_users,
    sync_status,
)
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_toolkit

from mcp.server.fastmcp import FastMCP

TOOL_MODULES = (
    search_users,
    get_student,
    list_teachers,
    list_groups,
    get_group,
    get_timetable,
    list_lessons,
    attendance_stats,
    missing_attendance,
    list_broadcasts,
    audit_log,
    sync_status,
)


def build_admin_server(deps: McpDeps) -> FastMCP:
    """Create the Administration server with all its tools registered."""
    kit = make_toolkit(
        deps,
        "admin",
        title="IHSP Administration",
        instructions_key="mcp-instructions-admin",
    )
    for module in TOOL_MODULES:
        module.register(kit)
    return kit.mcp
