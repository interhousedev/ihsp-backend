"""MCP servers, scopes and task presets (spec MCP-8)."""

from dataclasses import dataclass
from typing import Literal

from app.shared.actor import Role
from app.shared.lms_scopes import (
    COURSES_DELETE,
    COURSES_READ,
    COURSES_WRITE,
    LEGACY_ALIASES,
    MODULES_WRITE,
)
from app.shared.mcp_scopes import SCOPE_CATALOG, ScopeInfo

__all__ = ["SCOPE_CATALOG", "ScopeInfo"]

Server = Literal["student", "lms", "admin", "teacher"]
SERVERS: tuple[Server, ...] = ("student", "lms", "admin", "teacher")

# Roles that may connect to a server. For "lms" the real check (edit permission
# on some course) happens at call time (MCP-5).
ALLOWED_SERVER_ROLES: dict[str, frozenset[Role]] = {
    "student": frozenset({Role.STUDENT}),
    "lms": frozenset(
        {Role.TEACHER, Role.STUDENT, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.ADMIN}
    ),
    "admin": frozenset({Role.ADMIN}),
    "teacher": frozenset({Role.TEACHER, Role.ADMIN}),
}

AUDIENCE_BY_SERVER: dict[str, str] = {
    "student": "mcp-student",
    "lms": "mcp-lms",
    "admin": "mcp-admin",
    "teacher": "mcp-teacher",
}


@dataclass(frozen=True, slots=True)
class Preset:
    """A named set of scopes for a typical task."""

    key: str
    scopes: tuple[str, ...]


PRESETS: dict[str, tuple[Preset, ...]] = {
    "student": (
        Preset("study-planner", ("schedule:read", "homework:read", "materials:read")),
        Preset("grades", ("marks:read", "attendance:read")),
        Preset(
            "revision",
            ("materials:read", "files:read", "flashcards:read", "flashcards:write"),
        ),
    ),
    "lms": (
        Preset("course-reviewer", (COURSES_READ,)),
        Preset("module-editor", (COURSES_READ, MODULES_WRITE)),
        Preset("course-author", (COURSES_READ, COURSES_WRITE, MODULES_WRITE)),
        Preset(
            "course-manager",
            (COURSES_READ, COURSES_WRITE, COURSES_DELETE, MODULES_WRITE),
        ),
    ),
    "admin": (
        Preset("attendance-analyst", ("attendance:read", "groups:read")),
        Preset("timetable-viewer", ("timetable:read", "groups:read")),
    ),
    "teacher": (
        Preset("daily-planner", ("schedule:read", "groups:read", "journal:read")),
        Preset("gradebook", ("journal:read", "marks:read", "marks:write")),
        Preset(
            "classroom-assistant",
            ("schedule:read", "homework:write", "materials:generate"),
        ),
        Preset("lesson-planner", ("lesson-plans:write", "materials:generate")),
    ),
}


def scope_names(server: str) -> frozenset[str]:
    """All scopes of a server (the LMS also accepts its pre-split names)."""
    names = frozenset(info.scope for info in SCOPE_CATALOG.get(server, ()))
    return names | frozenset(LEGACY_ALIASES) if server == "lms" else names


def role_may_use_server(roles: frozenset[Role] | set[Role], server: str) -> bool:
    """True when one of the roles may connect to the server."""
    allowed = ALLOWED_SERVER_ROLES.get(server, frozenset())
    return bool(allowed & set(roles))


def server_from_audience(value: str) -> Server | None:
    """Map an audience name (`mcp-student`) to an MCP server (or None)."""
    for server in SERVERS:
        if value.strip() == AUDIENCE_BY_SERVER[server]:
            return server
    return None


def server_from_resource(value: str, mcp_base: str) -> Server | None:
    """Map an RFC 8707 resource to a server: only this deployment's exact URL."""
    cleaned = value.strip().rstrip("/")
    for server in SERVERS:
        if cleaned == f"{mcp_base.rstrip('/')}/{server}":
            return server
    return None
