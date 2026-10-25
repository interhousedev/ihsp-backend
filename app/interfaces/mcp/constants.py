"""Names, scopes, audiences and role rules of the three MCP servers (MCP-1, MCP-8)."""

from collections.abc import Mapping
from typing import Final, Literal

from app.shared.actor import Role
from app.shared.contracts.auth import (
    AUDIENCE_MCP_ADMIN,
    AUDIENCE_MCP_LMS,
    AUDIENCE_MCP_STUDENT,
)
from app.shared.lms_scopes import (
    COURSES_DELETE,
    COURSES_READ,
    COURSES_WRITE,
    MODULES_WRITE,
)

ServerName = Literal["student", "lms", "admin"]

SERVERS: Final[tuple[ServerName, ...]] = ("student", "lms", "admin")

# Every server is mounted under this prefix of the API app; in production nginx maps
# the host mcp.ihsu.uz to it.
MOUNT_PREFIX: Final = "/mcp"

CONNECTOR_TOKEN_PREFIX: Final = "ihsp_mcp_"

CALLS_PER_MINUTE: Final = 60

SCOPES_BY_SERVER: Final[Mapping[ServerName, tuple[str, ...]]] = {
    "student": (
        "schedule:read",
        "homework:read",
        "marks:read",
        "attendance:read",
        "materials:read",
        "files:read",
        "flashcards:read",
        "flashcards:write",
    ),
    "lms": (COURSES_READ, COURSES_WRITE, COURSES_DELETE, MODULES_WRITE),
    "admin": (
        "people:read",
        "groups:read",
        "timetable:read",
        "attendance:read",
        "broadcasts:read",
        "audit:read",
    ),
}

AUDIENCE_BY_SERVER: Final[Mapping[ServerName, str]] = {
    "student": AUDIENCE_MCP_STUDENT,
    "lms": AUDIENCE_MCP_LMS,
    "admin": AUDIENCE_MCP_ADMIN,
}

# Same table as identity's ALLOWED_SERVER_ROLES; checked again on every call so that a
# role removed after the token was issued stops working at once (MCP-5). For the LMS
# server the real check (edit permission on the course) is done by the LMS use cases.
ALLOWED_ROLES_BY_SERVER: Final[Mapping[ServerName, frozenset[Role]]] = {
    "student": frozenset({Role.STUDENT}),
    "lms": frozenset(
        {Role.TEACHER, Role.STUDENT, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.ADMIN}
    ),
    "admin": frozenset({Role.ADMIN}),
}

# The Administration server is read-only: only these names reach AdminToolBackend.
ADMIN_READ_TOOLS: Final = frozenset(
    {
        "search_users",
        "get_student",
        "list_teachers",
        "list_groups",
        "get_group",
        "get_timetable",
        "list_lessons",
        "attendance_stats",
        "missing_attendance",
        "list_broadcasts",
        "audit_log",
        "sync_status",
    }
)

# Language of tool error messages: they are read by AI clients, not by end users.
ERROR_LOCALE: Final = "en"
