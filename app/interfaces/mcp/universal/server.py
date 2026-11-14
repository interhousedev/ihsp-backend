"""The universal "app" MCP server: the student, teacher and LMS tools in one place.

Every tool keeps the behaviour of its source server: its guard checks the scope
`<source>:<scope>`, the cost class and the rate limits of the source, and re-checks the
caller's roles against the source server on every call. Names are prefixed too
(`student_get_marks`, `teacher_set_temporary_mark`, `lms_list_courses`), so the three
servers never clash. `tools/list` shows a caller only the tools of sources its roles
allow. Administration and the librarian have no place here.
"""

from typing import Any

from app.interfaces.mcp.auth import IhspAccessToken
from app.interfaces.mcp.constants import (
    ALLOWED_ROLES_BY_SERVER,
    APP_SOURCES,
    SourceServerName,
)
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_mcp
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.lms.server import TOOL_MODULES as LMS_MODULES
from app.interfaces.mcp.student.server import TOOL_MODULES as STUDENT_MODULES
from app.interfaces.mcp.teacher import ai_tools as teacher_ai_tools
from app.interfaces.mcp.teacher.server import TOOL_MODULES as TEACHER_MODULES
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.brand import current_brand

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

MODULES = {
    "student": STUDENT_MODULES,
    "teacher": TEACHER_MODULES,
    "lms": LMS_MODULES,
}


class AppMcp(FastMCP):
    """FastMCP whose `tools/list` hides the tools the caller's roles may not use."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Start without tools; `tool_sources` maps each tool to its source server."""
        super().__init__(*args, **kwargs)
        self.tool_sources: dict[str, SourceServerName] = {}

    async def list_tools(self) -> list[Tool]:
        """The tools whose source server allows one of the caller's roles."""
        tools = await super().list_tools()
        token = get_access_token()
        if not isinstance(token, IhspAccessToken):
            return []
        roles = token.actor.roles
        return [
            tool
            for tool in tools
            if roles & ALLOWED_ROLES_BY_SERVER[self.tool_sources[tool.name]]
        ]


def build_app_server(deps: McpDeps) -> FastMCP:
    """Create the universal server with the tools of its three sources registered."""
    mcp = make_mcp(
        deps,
        "app",
        title=f"{current_brand().name} App",
        instructions_key="mcp-instructions-app",
        cls=AppMcp,
    )
    assert isinstance(mcp, AppMcp)
    for source in APP_SOURCES:
        kit = ToolKit(
            mcp=mcp, deps=deps, guard=ToolGuard(deps, source, mounted_on="app")
        )
        for module in MODULES[source]:
            module.register(kit)
        if source == "teacher":
            teacher_ai_tools.register(kit)
        for name in kit.guard.registered:
            mcp.tool_sources[name] = source
    return mcp
