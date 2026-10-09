"""MCP servers, scopes and task presets (README MCP-8)."""

from dataclasses import dataclass
from typing import Literal

from app.shared.actor import Role

Server = Literal["student", "lms", "admin"]
SERVERS: tuple[Server, ...] = ("student", "lms", "admin")

# Roles that may connect to a server. For "lms" the real check (edit permission
# on some course) happens at call time (MCP-5).
ALLOWED_SERVER_ROLES: dict[str, frozenset[Role]] = {
    "student": frozenset({Role.STUDENT}),
    "lms": frozenset(
        {Role.TEACHER, Role.STUDENT, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.ADMIN}
    ),
    "admin": frozenset({Role.ADMIN}),
}

AUDIENCE_BY_SERVER: dict[str, str] = {
    "student": "mcp-student",
    "lms": "mcp-lms",
    "admin": "mcp-admin",
}


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """One scope and the tools it unlocks."""

    scope: str
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Preset:
    """A named set of scopes for a typical task."""

    key: str
    scopes: tuple[str, ...]


SCOPE_CATALOG: dict[str, tuple[ScopeInfo, ...]] = {
    "student": (
        ScopeInfo(
            "schedule:read",
            ("get_schedule", "get_my_subjects", "get_subject_lessons"),
        ),
        ScopeInfo("homework:read", ("get_homework",)),
        ScopeInfo("marks:read", ("get_marks", "get_results")),
        ScopeInfo("attendance:read", ("get_attendance",)),
        ScopeInfo("materials:read", ("get_lesson_materials",)),
        ScopeInfo("files:read", ("list_files", "read_file", "search_files")),
        ScopeInfo("flashcards:read", ("list_flashcard_sets", "get_flashcard_set")),
        ScopeInfo(
            "flashcards:write",
            ("create_flashcard_set", "add_flashcards", "update_flashcard"),
        ),
    ),
    "lms": (
        ScopeInfo(
            "courses:read",
            (
                "list_courses",
                "get_course",
                "get_step",
                "list_pending_changes",
                "list_versions",
                "list_attempts",
            ),
        ),
        ScopeInfo(
            "courses:draft",
            (
                "create_section",
                "create_step",
                "add_text_block",
                "add_test_block",
                "add_question",
                "add_flashcards_block",
            ),
        ),
    ),
    "admin": (
        ScopeInfo("people:read", ("search_users", "get_student", "list_teachers")),
        ScopeInfo("groups:read", ("list_groups", "get_group")),
        ScopeInfo("timetable:read", ("get_timetable", "list_lessons")),
        ScopeInfo("attendance:read", ("attendance_stats", "missing_attendance")),
        ScopeInfo("broadcasts:read", ("list_broadcasts",)),
        ScopeInfo("audit:read", ("audit_log", "sync_status")),
    ),
}

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
        Preset("course-reviewer", ("courses:read",)),
        Preset("course-author", ("courses:read", "courses:draft")),
    ),
    "admin": (
        Preset("attendance-analyst", ("attendance:read", "groups:read")),
        Preset("timetable-viewer", ("timetable:read", "groups:read")),
    ),
}


def scope_names(server: str) -> frozenset[str]:
    """All scopes of a server."""
    return frozenset(info.scope for info in SCOPE_CATALOG.get(server, ()))


def role_may_use_server(roles: frozenset[Role] | set[Role], server: str) -> bool:
    """True when one of the roles may connect to the server."""
    allowed = ALLOWED_SERVER_ROLES.get(server, frozenset())
    return bool(allowed & set(roles))


def server_from_resource(value: str) -> Server | None:
    """Map an audience or resource URL to an MCP server (or None)."""
    cleaned = value.strip().rstrip("/")
    for server in SERVERS:
        if cleaned == AUDIENCE_BY_SERVER[server]:
            return server
    last = cleaned.rsplit("/", 1)[-1]
    for server in SERVERS:
        if last == server and "/mcp" in cleaned:
            return server
    return None
