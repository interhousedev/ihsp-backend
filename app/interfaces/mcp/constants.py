"""Names, scopes, audiences and role rules of the three MCP servers (MCP-1, MCP-8)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast

from app.shared.actor import Role
from app.shared.contracts.auth import (
    AUDIENCE_MCP_ADMIN,
    AUDIENCE_MCP_APP,
    AUDIENCE_MCP_LMS,
    AUDIENCE_MCP_STUDENT,
    AUDIENCE_MCP_TEACHER,
)
from app.shared.mcp_scopes import SCOPE_NAMES_BY_SERVER

ServerName = Literal["student", "lms", "admin", "teacher", "app"]
SourceServerName = Literal["student", "lms", "teacher"]

SERVERS: Final[tuple[ServerName, ...]] = (
    "student",
    "lms",
    "admin",
    "teacher",
    "app",
)

# The universal server "app" serves the tools of these servers under prefixed names.
APP_SOURCES: Final[tuple[SourceServerName, ...]] = ("student", "teacher", "lms")

# Every server is mounted under this prefix of the API app; in production nginx maps
# the host mcp.ihsu.uz to it.
MOUNT_PREFIX: Final = "/mcp"

CONNECTOR_TOKEN_PREFIX: Final = "ihsp_mcp_"

CALLS_PER_MINUTE: Final = 60

# Second budget on top of the per-connector one: N connectors are not N budgets.
USER_CALLS_PER_MINUTE: Final = 120


@dataclass(frozen=True, slots=True)
class ToolLimit:
    """A cost class: `limit` calls per user in `window_seconds`, shared by its tools."""

    name: str
    limit: int
    window_seconds: int


AI_LIMIT: Final = ToolLimit("ai", 10, 60)  # model calls that cost tokens
WRITE_LIMIT: Final = ToolLimit("write", 30, 60)
SEARCH_LIMIT: Final = ToolLimit("search", 20, 60)  # text search and embeddings
EMIS_FETCH_LIMIT: Final = ToolLimit("emis", 30, 3600)
MEDIA_LINK_LIMIT: Final = ToolLimit("media", 60, 3600)

SCOPES_BY_SERVER: Final = cast(
    Mapping[ServerName, tuple[str, ...]], SCOPE_NAMES_BY_SERVER
)

AUDIENCE_BY_SERVER: Final[Mapping[ServerName, str]] = {
    "student": AUDIENCE_MCP_STUDENT,
    "lms": AUDIENCE_MCP_LMS,
    "admin": AUDIENCE_MCP_ADMIN,
    "teacher": AUDIENCE_MCP_TEACHER,
    "app": AUDIENCE_MCP_APP,
}

# Same table as identity's ALLOWED_SERVER_ROLES; checked again on every call so that a
# role removed after the token was issued stops working at once (MCP-5). For the LMS
# server the real check (edit permission on the course) is done by the LMS use cases.
_SOURCE_ROLES: Final[Mapping[SourceServerName, frozenset[Role]]] = {
    "student": frozenset({Role.STUDENT}),
    "lms": frozenset(
        {Role.TEACHER, Role.STUDENT, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.ADMIN}
    ),
    "teacher": frozenset({Role.TEACHER, Role.ADMIN}),
}
# "app": the union of its sources; each tool is re-checked against its own source.
ALLOWED_ROLES_BY_SERVER: Final[Mapping[ServerName, frozenset[Role]]] = {
    "student": _SOURCE_ROLES["student"],
    "lms": _SOURCE_ROLES["lms"],
    "teacher": _SOURCE_ROLES["teacher"],
    "admin": frozenset({Role.ADMIN}),
    "app": frozenset().union(*_SOURCE_ROLES.values()),
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
        "find_feature",
    }
)

# Language of tool error messages: they are read by AI clients, not by end users.
ERROR_LOCALE: Final = "en"
