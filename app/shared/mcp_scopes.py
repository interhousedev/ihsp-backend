"""The one registry of MCP scopes, their tools and the releases that added them.

`app/interfaces/mcp/constants.py` and `app/modules/identity/domain/scopes.py` read these
tables, so the interface and the connector pages cannot drift apart (MCP-8).

Releases are append-only: an id already offered to users never changes. A release lists
scopes of one server only. Administration is never offered: its connectors need an OTP
step-up at creation, and a button would bypass that.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.shared.lms_scopes import (
    COURSES_DELETE,
    COURSES_READ,
    COURSES_WRITE,
    MODULES_WRITE,
)

Server = Literal["student", "lms", "admin"]

BASELINE: Final = "baseline"
RELEASE_2026_11: Final = "2026-11-mcp-1"


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """One scope, the tools it unlocks and what it means for consent."""

    scope: str
    tools: tuple[str, ...]
    write: bool = False
    since: str = BASELINE
    widens: tuple[str, ...] = ()
    """Existing tools (of other scopes) that see more with this scope."""


@dataclass(frozen=True, slots=True)
class ScopeRelease:
    """Scopes added together, offered to existing connectors of one server."""

    id: str
    server: Server
    scopes: tuple[str, ...]
    summary_key: str


SCOPE_CATALOG: Final[dict[str, tuple[ScopeInfo, ...]]] = {
    "student": (
        ScopeInfo(
            "schedule:read",
            ("get_schedule", "get_my_subjects", "get_subject_lessons"),
        ),
        ScopeInfo("homework:read", ("get_homework",)),
        ScopeInfo("marks:read", ("get_marks", "get_results", "get_gpa")),
        ScopeInfo("attendance:read", ("get_attendance",)),
        ScopeInfo("materials:read", ("get_lesson_materials", "get_lesson_detail")),
        ScopeInfo("files:read", ("list_files", "read_file", "search_files")),
        ScopeInfo("flashcards:read", ("list_flashcard_sets", "get_flashcard_set")),
        ScopeInfo(
            "flashcards:write",
            (
                "create_flashcard_set",
                "add_flashcards",
                "update_flashcard",
                "update_flashcard_set",
                "batch_edit_flashcards",
            ),
            write=True,
        ),
        ScopeInfo(
            "sync:run",
            ("refresh_my_marks", "get_sync_status"),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "teachers:read",
            ("get_my_teachers", "get_teacher_timetable"),
            since=RELEASE_2026_11,
        ),
        ScopeInfo("knowledge:read", ("search_knowledge",), since=RELEASE_2026_11),
        ScopeInfo(
            "flashcards:delete",
            ("delete_flashcards",),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo("tests:read", ("list_tests", "get_test"), since=RELEASE_2026_11),
        ScopeInfo(
            "tests:write",
            ("create_test", "batch_edit_test_questions"),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "notebooks:read",
            (
                "list_notebooks",
                "get_notebook",
                "search_notebooks",
                "read_notebook_source",
                "list_notebook_outputs",
            ),
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "notebooks:write",
            ("create_notebook", "add_notebook_sources", "generate_notebook_output"),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "library:read",
            ("search_library", "get_library_item", "read_library_text"),
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "files:read.all",
            (),
            since=RELEASE_2026_11,
            widens=("list_files", "search_files", "read_file"),
        ),
        # Not "courses:read": that name is a legacy alias of LMS authoring scopes.
        ScopeInfo(
            "learning:read",
            (
                "list_my_courses",
                "get_course_curriculum",
                "get_course_step",
                "get_course_media_link",
            ),
            since=RELEASE_2026_11,
        ),
    ),
    "lms": (
        ScopeInfo(
            COURSES_READ,
            (
                "list_courses",
                "get_course",
                "get_step",
                "list_pending_changes",
                "list_versions",
                "list_attempts",
            ),
        ),
        ScopeInfo(COURSES_WRITE, ("create_course", "update_course"), write=True),
        ScopeInfo(COURSES_DELETE, ("delete_course",), write=True),
        ScopeInfo(
            MODULES_WRITE,
            (
                "create_module",
                "update_module",
                "delete_module",
                "create_section",
                "create_step",
                "update_step",
                "delete_step",
                "add_text_block",
                "add_test_block",
                "add_question",
                "add_flashcards_block",
            ),
            write=True,
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

# Tools under a write scope that only read (the status of the action of that scope).
READ_ONLY_TOOLS_IN_WRITE_SCOPES: Final = frozenset({"get_sync_status"})

RELEASES: Final[tuple[ScopeRelease, ...]] = (
    ScopeRelease(
        id=RELEASE_2026_11,
        server="student",
        scopes=(
            "sync:run",
            "teachers:read",
            "knowledge:read",
            "flashcards:delete",
            "tests:read",
            "tests:write",
            "notebooks:read",
            "notebooks:write",
            "library:read",
            "files:read.all",
            "learning:read",
        ),
        summary_key="mcp-release-2026-11-mcp-1",
    ),
)

OFFERABLE_SERVERS: Final[frozenset[Server]] = frozenset({"student", "lms"})

SCOPE_NAMES_BY_SERVER: Final[Mapping[str, tuple[str, ...]]] = {
    server: tuple(info.scope for info in infos)
    for server, infos in SCOPE_CATALOG.items()
}


def scope_info(server: str, scope: str) -> ScopeInfo:
    """The entry of a scope; KeyError when the server has no such scope."""
    for info in SCOPE_CATALOG[server]:
        if info.scope == scope:
            return info
    raise KeyError(f"{server}/{scope}")


def server_tools(server: str) -> frozenset[str]:
    """Every tool the registry names on a server."""
    return frozenset(t for info in SCOPE_CATALOG[server] for t in info.tools)


def tool_scope(server: str, tool: str) -> str:
    """The scope a tool needs; KeyError when the registry does not name it."""
    for info in SCOPE_CATALOG[server]:
        if tool in info.tools:
            return info.scope
    raise KeyError(f"{server}/{tool}")
