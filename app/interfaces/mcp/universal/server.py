"""The universal "app" MCP server: the student, teacher and LMS tools in one place.

Every tool keeps the behaviour of its source server: its guard checks the scope
`<source>:<scope>`, the cost class and the rate limits of the source, and re-checks the
caller's roles against the source server on every call. Names are prefixed too
(`student_get_marks`, `teacher_set_temporary_mark`, `lms_list_courses`), so the three
servers never clash. `tools/list` shows the catalog's meta tools and a few pinned
tools; search and describe show a caller only the tools of sources its roles allow.
Administration and the librarian have no place here.
"""

from app.interfaces.mcp.catalog import CatalogMcp, enable_catalog
from app.interfaces.mcp.constants import APP_SOURCES, SourceServerName
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.factory import make_mcp
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.lms.server import TOOL_MODULES as LMS_MODULES
from app.interfaces.mcp.student.server import TOOL_MODULES as STUDENT_MODULES
from app.interfaces.mcp.teacher import ai_tools as teacher_ai_tools
from app.interfaces.mcp.teacher.server import TOOL_MODULES as TEACHER_MODULES
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.brand import current_brand

from mcp.server.fastmcp import FastMCP

PINNED = (
    "student_find_feature",
    "student_get_schedule",
    "student_get_homework",
    "teacher_find_feature",
    "teacher_get_today",
    "teacher_get_timetable",
    "lms_list_courses",
)

MODULES = {
    "student": STUDENT_MODULES,
    "teacher": TEACHER_MODULES,
    "lms": LMS_MODULES,
}


def build_app_server(deps: McpDeps) -> FastMCP:
    """Create the universal server with the tools of its three sources registered."""
    mcp = make_mcp(
        deps,
        "app",
        title=f"{current_brand().name} App",
        instructions_key="mcp-instructions-app",
        cls=CatalogMcp,
    )
    assert isinstance(mcp, CatalogMcp)
    sources: dict[str, SourceServerName] = {}
    for source in APP_SOURCES:
        kit = ToolKit(
            mcp=mcp, deps=deps, guard=ToolGuard(deps, source, mounted_on="app")
        )
        for module in MODULES[source]:
            module.register(kit)
        if source == "teacher":
            teacher_ai_tools.register(kit)
        for name in kit.guard.registered:
            sources[name] = source
    enable_catalog(mcp, sources, PINNED)
    return mcp
