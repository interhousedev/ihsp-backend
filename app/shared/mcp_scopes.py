"""The one registry of MCP scopes, their tools and the releases that added them.

`app/interfaces/mcp/constants.py` and `app/modules/identity/domain/scopes.py` read these
tables, so the interface and the connector pages cannot drift apart (MCP-8).

Releases are append-only: an id already offered to users never changes. A release lists
scopes of one server only. Administration is never offered: its connectors need an OTP
step-up at creation, and a button would bypass that.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.shared.actor import Role
from app.shared.lms_scopes import (
    COURSES_DELETE,
    COURSES_READ,
    COURSES_WRITE,
    MODULES_WRITE,
)

Server = Literal["student", "lms", "admin", "teacher", "app", "admission"]
SourceServer = Literal["student", "lms", "teacher", "admission"]

# The universal server "app" serves these servers' tools, each name and scope prefixed
# by its source server (`teacher_get_journal`, `teacher:journal:read`).
APP_SOURCES: Final[tuple[SourceServer, ...]] = (
    "student",
    "teacher",
    "lms",
    "admission",
)

# Admission: applicants (students) and admission staff share one server; each tool
# and each scope says which family may use it.
ADMISSION_APPLICANT_ROLES: Final = frozenset({Role.STUDENT})
ADMISSION_STAFF_ROLES: Final = frozenset(
    {Role.COUNSELOR, Role.MENTOR, Role.TRANSCRIPT_OFFICER, Role.ADMIN}
)
ADMISSION_ROLES: Final = ADMISSION_APPLICANT_ROLES | ADMISSION_STAFF_ROLES

BASELINE: Final = "baseline"
RELEASE_2026_11: Final = "2026-11-mcp-1"
RELEASE_2026_12: Final = "2026-12-mcp-1"
RELEASE_2026_12_2: Final = "2026-12-mcp-2"
RELEASE_2026_12_3: Final = "2026-12-mcp-3"  # student: clubs
RELEASE_2026_12_4: Final = "2026-12-mcp-4"  # student: learning record
RELEASE_2026_12_5: Final = "2026-12-mcp-5"  # teacher: homework review
RELEASE_2026_12_6: Final = "2026-12-mcp-6"  # admission: the whole server


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """One scope, the tools it unlocks and what it means for consent."""

    scope: str
    tools: tuple[str, ...]
    write: bool = False
    since: str = BASELINE
    widens: tuple[str, ...] = ()
    """Existing tools (of other scopes) that see more with this scope."""
    roles: frozenset[Role] = frozenset()
    """Roles that may hold this scope; empty means every role of the server."""


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
            ("get_schedule", "get_my_subjects", "get_subject_lessons", "find_feature"),
        ),
        ScopeInfo("homework:read", ("get_homework", "get_homework_submission")),
        ScopeInfo(
            "marks:read",
            ("get_marks", "get_results", "get_gpa"),
            widens=("get_learning_record",),
        ),
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
                "get_notebook_chat",
                "get_notebook_notes",
            ),
            since=RELEASE_2026_11,
        ),
        ScopeInfo("chats:read", ("list_chats", "get_chat"), since=RELEASE_2026_12),
        ScopeInfo("group:read", ("get_my_group",), since=RELEASE_2026_12_2),
        ScopeInfo("rating_book:read", ("get_rating_book",), since=RELEASE_2026_12_2),
        ScopeInfo(
            "notifications:read", ("list_notifications",), since=RELEASE_2026_12_2
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
        ScopeInfo(
            "files:write",
            ("upload_file",),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "homework:submit",
            ("submit_homework", "withdraw_homework_submission"),
            write=True,
            since=RELEASE_2026_11,
        ),
        ScopeInfo(
            "clubs:read",
            (
                "list_my_clubs",
                "list_club_events",
                "get_club_event",
                "list_club_announcements",
                "list_event_media",
            ),
            since=RELEASE_2026_12_3,
        ),
        ScopeInfo(
            "clubs:write",
            (
                "create_club_event",
                "update_club_event",
                "publish_club_event",
                "upload_club_media",
                "set_event_cover",
                "add_event_media",
                "send_club_announcement",
                "cancel_club_event",
                "cancel_club_announcement",
                "delete_club_media",
            ),
            write=True,
            since=RELEASE_2026_12_3,
        ),
        ScopeInfo(
            "progress:read",
            (
                "get_learning_record",
                "get_my_course_progress",
                "list_my_attempts",
                "get_my_attempt",
                "list_my_ai_reviews",
                "get_my_ai_review",
                "list_my_certificates",
                "list_my_badges",
            ),
            since=RELEASE_2026_12_4,
        ),
    ),
    "lms": (
        ScopeInfo(
            COURSES_READ,
            (
                "list_courses",
                "get_course",
                "get_step",
                "list_block_types",
                "list_pending_changes",
                "list_versions",
                "list_attempts",
                "find_feature",
                "get_settings",
                "list_staff",
                "list_students",
                "course_progress",
                "get_attempt",
                "list_ai_review_submissions",
            ),
        ),
        ScopeInfo(
            COURSES_WRITE,
            (
                "create_course",
                "update_course",
                "publish",
                "restore_version",
                "update_settings",
                "add_staff",
                "remove_staff",
                "set_access",
                "override_score",
            ),
            write=True,
        ),
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
                "add_block",
                "add_question",
                "move_section",
                "move_step",
                "move_block",
                "move_question",
                "update_block",
                "delete_block",
                "update_question",
                "delete_question",
                "build_course",
                "generate_course_draft",
                "generate_lesson",
            ),
            write=True,
        ),
    ),
    "admin": (
        ScopeInfo(
            "people:read",
            ("search_users", "get_student", "list_teachers", "find_feature"),
        ),
        ScopeInfo("groups:read", ("list_groups", "get_group")),
        ScopeInfo("timetable:read", ("get_timetable", "list_lessons")),
        ScopeInfo("attendance:read", ("attendance_stats", "missing_attendance")),
        ScopeInfo("broadcasts:read", ("list_broadcasts",)),
        ScopeInfo(
            "audit:read",
            (
                "audit_log",
                "sync_status",
                "ai_list_requests",
                "ai_list_prompts",
                "ai_prompt_versions",
                "ai_prompt_diff",
                "ai_request_stats",
                "ai_spend",
                "ai_pipelines",
            ),
        ),
    ),
    "teacher": (
        ScopeInfo(
            "schedule:read",
            ("get_today", "get_timetable", "get_lesson", "find_feature"),
        ),
        ScopeInfo("groups:read", ("list_my_groups", "get_group_roster")),
        ScopeInfo(
            "journal:read",
            ("get_journal", "get_group_attendance", "my_missing_attendance"),
        ),
        ScopeInfo(
            "homework:read",
            (
                "list_homework_lessons",
                "list_homework_submissions",
                "get_homework_submission",
                "get_homework_preferences",
            ),
        ),
        ScopeInfo(
            "homework:write",
            (
                "set_homework",
                "clear_homework",
                "set_homework_settings",
                "set_homework_preferences",
            ),
            write=True,
        ),
        ScopeInfo("marks:read", ("list_temporary_marks", "get_student_record")),
        ScopeInfo(
            "marks:write",
            ("set_temporary_mark", "delete_temporary_mark"),
            write=True,
        ),
        ScopeInfo("assessments:read", ("list_assessments",)),
        ScopeInfo(
            "assessments:write",
            ("create_assessment", "update_assessment"),
            write=True,
        ),
        ScopeInfo("workoffs:read", ("get_unfinished_work_report",)),
        ScopeInfo(
            "materials:generate",
            (
                "generate_questions",
                "generate_handout",
                "check_student_work",
                "check_ai_authorship",
            ),
        ),
        ScopeInfo("lesson-plans:read", ("list_plan_templates",)),
        ScopeInfo(
            "lesson-plans:write",
            ("register_plan_template", "generate_lesson_plan"),
            write=True,
        ),
        ScopeInfo("files:write", ("upload_file",), write=True),
        ScopeInfo("notifications:read", ("list_notifications",)),
        ScopeInfo(
            "homework:review",
            ("review_homework_submission", "clear_homework_review"),
            write=True,
            since=RELEASE_2026_12_5,
        ),
    ),
    "admission": (
        ScopeInfo(
            "application:read",
            (
                "get_application",
                "get_today",
                "get_profile",
                "list_activities",
                "list_honor_suggestions",
                "list_certificate_proofs",
                "list_test_scores",
                "list_tasks",
                "get_readiness",
                "list_checklist",
                "get_school_grades",
                "get_my_university_list",
            ),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "application:write",
            (
                "update_profile",
                "add_activity",
                "update_activity",
                "delete_activity",
                "add_test_score",
                "update_test_score",
                "delete_test_score",
                "link_activity_opportunity",
            ),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "documents:read",
            ("list_documents", "read_document"),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "documents:write",
            ("upload_document", "add_certificate_proof"),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "plans:read",
            ("get_goal_plan", "get_opportunity_plan"),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "plans:write",
            (
                "add_milestone",
                "update_milestone",
                "delete_milestone",
                "suggest_goal_plan",
                "plan_opportunity",
                "unplan_opportunity",
                "generate_opportunity_plan",
                "add_external_opportunity",
                "update_external_opportunity",
                "remove_external_opportunity",
            ),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "catalog:read",
            (
                "search_universities",
                "get_university",
                "search_opportunities",
                "get_opportunity",
                "get_country",
            ),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_ROLES,
        ),
        ScopeInfo(
            "consents:read",
            ("list_consents",),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "memory:read",
            ("list_memory_notes",),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "memory:write",
            ("write_memory_note", "delete_memory_note"),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "calendar:read",
            ("get_calendar", "export_calendar_ics", "get_calendar_feed"),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "calendar:write",
            ("create_calendar_feed", "replace_calendar_feed", "revoke_calendar_feed"),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_APPLICANT_ROLES,
        ),
        ScopeInfo(
            "caseload:read",
            ("list_caseload", "list_caseload_deadlines", "list_document_queue"),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_STAFF_ROLES,
        ),
        ScopeInfo(
            "students:read",
            (
                "get_student_application",
                "get_student_readiness",
                "list_student_reviews",
                "get_student_review",
                "list_student_documents",
                "read_student_document",
                "list_comments",
            ),
            since=RELEASE_2026_12_6,
            roles=ADMISSION_STAFF_ROLES,
        ),
        ScopeInfo(
            "students:write",
            ("add_comment", "delete_comment", "assign_task"),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_STAFF_ROLES,
        ),
        ScopeInfo(
            "documents:review",
            ("review_document",),
            write=True,
            since=RELEASE_2026_12_6,
            roles=ADMISSION_STAFF_ROLES,
        ),
    ),
}

# Tools under a write scope that only read (the status of the action of that scope).
READ_ONLY_TOOLS_IN_WRITE_SCOPES: Final = frozenset(
    {"get_sync_status", "student_get_sync_status"}
)

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
            "files:write",
            "homework:submit",
        ),
        summary_key="mcp-release-2026-11-mcp-1",
    ),
    ScopeRelease(
        id=RELEASE_2026_12,
        server="student",
        scopes=("chats:read",),
        summary_key="mcp-release-2026-12-mcp-1",
    ),
    ScopeRelease(
        id=RELEASE_2026_12_2,
        server="student",
        scopes=("group:read", "rating_book:read", "notifications:read"),
        summary_key="mcp-release-2026-12-mcp-2",
    ),
    ScopeRelease(
        id=RELEASE_2026_12_3,
        server="student",
        scopes=("clubs:read", "clubs:write"),
        summary_key="mcp-release-2026-12-mcp-3",
    ),
    ScopeRelease(
        id=RELEASE_2026_12_4,
        server="student",
        scopes=("progress:read",),
        summary_key="mcp-release-2026-12-mcp-4",
    ),
    # Teacher and admission are not offerable: these records only date their scopes.
    ScopeRelease(
        id=RELEASE_2026_12_5,
        server="teacher",
        scopes=("homework:review",),
        summary_key="mcp-release-2026-12-mcp-5",
    ),
    ScopeRelease(
        id=RELEASE_2026_12_6,
        server="admission",
        scopes=tuple(info.scope for info in SCOPE_CATALOG["admission"]),
        summary_key="mcp-release-2026-12-mcp-6",
    ),
)

SCOPE_CATALOG["app"] = tuple(
    ScopeInfo(
        f"{source}:{info.scope}",
        tools=tuple(f"{source}_{tool}" for tool in info.tools),
        write=info.write,
        since=info.since,
        widens=tuple(f"{source}_{tool}" for tool in info.widens),
        roles=info.roles,
    )
    for source in APP_SOURCES
    for info in SCOPE_CATALOG[source]
)

OFFERABLE_SERVERS: Final[frozenset[Server]] = frozenset({"student", "lms"})

# Old admission personal-token (`ihsp_pat_`) scopes and the server scopes they stand
# for (same tools as before). A personal token never yields a staff scope.
PAT_SCOPE_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "admission:read": (
        "application:read",
        "plans:read",
        "catalog:read",
        "consents:read",
        "memory:read",
        "calendar:read",
    ),
    "admission:memory": ("memory:read", "memory:write"),
    "admission:documents": ("documents:read",),
    "admission:docs": ("documents:write",),
}


def pat_scopes(scopes: Collection[str]) -> frozenset[str]:
    """Admission server scopes of old personal-token scopes; unknown ones drop."""
    return frozenset(new for old in scopes for new in PAT_SCOPE_ALIASES.get(old, ()))


def scopes_for_roles(server: str, roles: Collection[Role]) -> frozenset[str]:
    """Scopes of a server that one of the roles may hold (per-scope role lists)."""
    held = frozenset(roles)
    return frozenset(
        info.scope
        for info in SCOPE_CATALOG[server]
        if not info.roles or info.roles & held
    )


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
