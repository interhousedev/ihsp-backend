"""MCP-1, MCP-6, MCP-8: the exact tools of each server and their scopes."""

import re
from typing import Any

from app.interfaces.mcp.constants import ADMIN_READ_TOOLS, SCOPES_BY_SERVER, ServerName
from app.shared.mcp_scopes import (
    READ_ONLY_TOOLS_IN_WRITE_SCOPES,
    SCOPE_CATALOG,
    server_tools,
    tool_scope,
)
from tests.mcp import pending_academic, pending_content, pending_files_courses
from tests.mcp.conftest import World
from tests.mcp.helpers import call, text_of

import pytest
from mcp.types import Tool

# Tools in the registry whose package has not landed; each package shrinks its own.
PENDING = (
    pending_academic.PENDING | pending_content.PENDING | pending_files_courses.PENDING
)

COURSE = "00000000-0000-0000-0000-0000000000c1"
STEP = "00000000-0000-0000-0000-0000000000a1"
ID = "00000000-0000-0000-0000-000000000001"
CARDS = [{"front": "f", "back": "b"}]
QUESTION = {
    "type": "single",
    "prompt": "2+2?",
    "options": [{"text": "4", "correct": True}, {"text": "5"}],
}

# tool -> (scope of MCP-8, minimal valid arguments)
STUDENT_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "get_schedule": ("schedule:read", {}),
    "find_feature": ("schedule:read", {"query": "marks"}),
    "get_my_subjects": ("schedule:read", {}),
    "get_subject_lessons": ("schedule:read", {"subject_id": ID}),
    "get_homework": ("homework:read", {}),
    "get_marks": ("marks:read", {}),
    "get_results": ("marks:read", {}),
    "get_attendance": ("attendance:read", {}),
    "get_lesson_materials": ("materials:read", {"lesson_id": ID}),
    "list_files": ("files:read", {}),
    "read_file": ("files:read", {"file_id": ID}),
    "search_files": ("files:read", {"query": "x"}),
    "list_flashcard_sets": ("flashcards:read", {}),
    "get_flashcard_set": ("flashcards:read", {"set_id": ID}),
    "create_flashcard_set": ("flashcards:write", {"title": "t", "cards": CARDS}),
    "add_flashcards": ("flashcards:write", {"set_id": ID, "cards": CARDS}),
    "update_flashcard": ("flashcards:write", {"card_id": ID, "front": "x"}),
}
LMS_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "list_courses": ("lms.courses.read", {}),
    "find_feature": ("lms.courses.read", {"query": "courses"}),
    "get_course": ("lms.courses.read", {"course_id": COURSE}),
    "get_step": ("lms.courses.read", {"step_id": STEP}),
    "list_pending_changes": ("lms.courses.read", {"course_id": COURSE}),
    "list_versions": ("lms.courses.read", {"course_id": COURSE}),
    "list_attempts": ("lms.courses.read", {"course_id": COURSE}),
    "create_course": ("lms.courses.write", {"title": "t"}),
    "update_course": ("lms.courses.write", {"course_id": COURSE, "title": "t"}),
    "delete_course": ("lms.courses.delete", {"course_id": COURSE}),
    "create_module": ("lms.modules.write", {"course_id": COURSE, "title": "t"}),
    "update_module": (
        "lms.modules.write",
        {"course_id": COURSE, "module_id": "s", "title": "t"},
    ),
    "delete_module": ("lms.modules.write", {"course_id": COURSE, "module_id": "s"}),
    "create_section": ("lms.modules.write", {"course_id": COURSE, "title": "t"}),
    "create_step": (
        "lms.modules.write",
        {"course_id": COURSE, "section_id": "s", "title": "t"},
    ),
    "update_step": ("lms.modules.write", {"step_id": STEP, "title": "t"}),
    "delete_step": ("lms.modules.write", {"step_id": STEP}),
    "add_text_block": ("lms.modules.write", {"step_id": STEP, "markdown": "m"}),
    "add_test_block": ("lms.modules.write", {"step_id": STEP}),
    "add_question": (
        "lms.modules.write",
        {"step_id": STEP, "block_id": "b", "question": QUESTION},
    ),
    "add_flashcards_block": ("lms.modules.write", {"step_id": STEP, "cards": CARDS}),
    "move_section": (
        "lms.modules.write",
        {"course_id": COURSE, "section_id": "s", "position": 0},
    ),
    "move_step": (
        "lms.modules.write",
        {"course_id": COURSE, "step_id": STEP, "to_section_id": "s", "position": 0},
    ),
    "move_block": (
        "lms.modules.write",
        {"step_id": STEP, "block_id": "b", "position": 0},
    ),
    "move_question": (
        "lms.modules.write",
        {"step_id": STEP, "block_id": "b", "question_id": "q", "position": 0},
    ),
    "update_block": (
        "lms.modules.write",
        {
            "step_id": STEP,
            "block_id": "b",
            "block": {"type": "text", "markdown": "m"},
        },
    ),
    "delete_block": ("lms.modules.write", {"step_id": STEP, "block_id": "b"}),
    "update_question": (
        "lms.modules.write",
        {"step_id": STEP, "block_id": "b", "question_id": "q", "question": QUESTION},
    ),
    "delete_question": (
        "lms.modules.write",
        {"step_id": STEP, "block_id": "b", "question_id": "q"},
    ),
    "build_course": (
        "lms.modules.write",
        {
            "course_id": COURSE,
            "sections": [{"title": "t", "steps": [{"title": "t"}]}],
        },
    ),
    "generate_course_draft": ("lms.modules.write", {"topic": "Algebra"}),
    "generate_lesson": ("lms.modules.write", {"topic": "Algebra"}),
    "publish": ("lms.courses.write", {"course_id": COURSE}),
    "restore_version": ("lms.courses.write", {"course_id": COURSE, "number": 1}),
    "update_settings": ("lms.courses.write", {"course_id": COURSE}),
    "add_staff": (
        "lms.courses.write",
        {"course_id": COURSE, "login": "t1", "role": "teacher"},
    ),
    "remove_staff": ("lms.courses.write", {"course_id": COURSE, "user_id": ID}),
    "override_score": (
        "lms.courses.write",
        {"attempt_id": ID, "score": 5, "comment": "ok"},
    ),
    "get_settings": ("lms.courses.read", {"course_id": COURSE}),
    "list_staff": ("lms.courses.read", {"course_id": COURSE}),
    "list_students": ("lms.courses.read", {"course_id": COURSE}),
    "course_progress": ("lms.courses.read", {"course_id": COURSE}),
    "get_attempt": ("lms.courses.read", {"attempt_id": ID}),
}
ADMIN_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "search_users": ("people:read", {"query": "x"}),
    "find_feature": ("people:read", {"query": "users"}),
    "get_student": ("people:read", {"user_id": ID}),
    "list_teachers": ("people:read", {}),
    "list_groups": ("groups:read", {}),
    "get_group": ("groups:read", {"group_id": ID}),
    "get_timetable": ("timetable:read", {}),
    "list_lessons": ("timetable:read", {}),
    "attendance_stats": ("attendance:read", {}),
    "missing_attendance": ("attendance:read", {}),
    "list_broadcasts": ("broadcasts:read", {}),
    "audit_log": ("audit:read", {}),
    "sync_status": ("audit:read", {}),
}
CATALOG: dict[ServerName, dict[str, tuple[str, dict[str, Any]]]] = {
    "student": STUDENT_TOOLS,
    "lms": LMS_TOOLS,
    "admin": ADMIN_TOOLS,
}


def _writers(tools: list[Tool]) -> set[str]:
    """Names of tools that are not marked read-only."""
    return {
        tool.name
        for tool in tools
        if tool.annotations is None or not tool.annotations.readOnlyHint
    }


FORBIDDEN_VERBS = re.compile(r"delete|remove|publish|restore|discard|drop|destroy")
LMS_FORBIDDEN_VERBS = re.compile(r"discard|drop|destroy")


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_server_offers_exactly_the_tools_of_mcp_8(
    world: World, server: ServerName
) -> None:
    """MCP-8: the tools of each server, nothing else."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])

    async with world.session(server, token) as session:
        listed = await session.list_tools()

    assert {tool.name for tool in listed.tools} == server_tools(server) - PENDING


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
def test_this_catalog_table_is_the_registry(server: ServerName) -> None:
    """MCP-8: the argument table below agrees with the scope registry."""
    for name, (scope, _) in CATALOG[server].items():
        assert tool_scope(server, name) == scope, name


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_no_server_has_a_publish_tool_and_only_lms_deletes(
    world: World, server: ServerName
) -> None:
    """MCP-6: only the LMS server publishes or deletes."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])

    async with world.session(server, token) as session:
        listed = await session.list_tools()

    names = [tool.name for tool in listed.tools]
    forbidden = LMS_FORBIDDEN_VERBS if server == "lms" else FORBIDDEN_VERBS
    # The one student delete: own cards only, under its own scope (`flashcards:delete`).
    assert not [
        name for name in names if forbidden.search(name) and name != "delete_flashcards"
    ]
    assert ("create_course" in names) == (server == "lms")


async def test_lms_server_writes_drafts_and_course_operations(world: World) -> None:
    """MCP-6: the LMS writers are the draft CRUD and the course operations."""
    token, _ = world.connector_token("lms", *SCOPES_BY_SERVER["lms"])

    async with world.session("lms", token) as session:
        listed = await session.list_tools()

    writers = _writers(listed.tools)
    assert writers == {
        "create_course",
        "update_course",
        "delete_course",
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
        "move_section",
        "move_step",
        "move_block",
        "move_question",
        "update_block",
        "delete_block",
        "update_question",
        "delete_question",
        "build_course",
        "publish",
        "restore_version",
        "update_settings",
        "add_staff",
        "remove_staff",
        "override_score",
        "generate_course_draft",
        "generate_lesson",
    }
    destructive = {
        t.name
        for t in listed.tools
        if t.annotations is not None and t.annotations.destructiveHint
    }
    assert destructive == {
        "delete_course",
        "delete_module",
        "delete_step",
        "delete_block",
        "delete_question",
        "remove_staff",
    }


async def test_students_server_writes_only_under_write_scopes(
    world: World,
) -> None:
    """MCP-6: the Students write tools are those the registry calls writes."""
    token, _ = world.connector_token("student", *SCOPES_BY_SERVER["student"])

    async with world.session("student", token) as session:
        listed = await session.list_tools()

    expected = {
        tool
        for info in SCOPE_CATALOG["student"]
        if info.write
        for tool in info.tools
        if tool not in READ_ONLY_TOOLS_IN_WRITE_SCOPES
    }
    assert _writers(listed.tools) == expected - PENDING


async def test_administration_server_is_read_only(world: World) -> None:
    """MCP-1: every Administration tool is read-only and on the read list."""
    token, _ = world.connector_token("admin", *SCOPES_BY_SERVER["admin"])

    async with world.session("admin", token) as session:
        listed = await session.list_tools()

    assert {tool.name for tool in listed.tools} == ADMIN_READ_TOOLS
    assert _writers(listed.tools) == set()


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_every_tool_needs_its_scope_from_mcp_8(
    world: World, server: ServerName
) -> None:
    """MCP-8: a connector holding every scope except the tool's own is refused."""
    async with world.serve() as running:
        for name, (scope, arguments) in CATALOG[server].items():
            others = [s for s in SCOPES_BY_SERVER[server] if s != scope]
            token, _ = world.connector_token(server, *others)
            async with running.session(server, token) as session:
                result = await call(session, name, **arguments)

            assert result.isError, name
            assert "insufficient_scope" in text_of(result), name
            assert scope in text_of(result), name


async def test_tools_describe_their_arguments_for_ai_clients(world: World) -> None:
    """Typed parameters with descriptions (MCP-8)."""
    token, _ = world.connector_token("student", *SCOPES_BY_SERVER["student"])

    async with world.session("student", token) as session:
        listed = await session.list_tools()

    by_name = {tool.name: tool for tool in listed.tools}
    schema = by_name["get_marks"].inputSchema["properties"]
    assert schema["subject_id"]["description"]
    assert schema["date_from"]["description"]
    assert by_name["read_file"].description
    assert by_name["read_file"].inputSchema["required"] == ["file_id"]


async def test_a_tool_that_rotates_a_grant_is_not_idempotent(world: World) -> None:
    """MCP-B5: asking twice for a media link kills the first link."""
    token, _ = world.connector_token("student", *SCOPES_BY_SERVER["student"])

    async with world.session("student", token) as session:
        listed = await session.list_tools()

    by_name = {tool.name: tool for tool in listed.tools}
    media = by_name["get_course_media_link"].annotations
    assert media is not None and media.idempotentHint is False
    plain = by_name["list_files"].annotations
    assert plain is not None and plain.idempotentHint is True


TEACHER_SCOPES = {
    "schedule:read": {"get_today", "get_timetable", "get_lesson", "find_feature"},
    "groups:read": {"list_my_groups", "get_group_roster"},
    "journal:read": {"get_journal", "get_group_attendance", "my_missing_attendance"},
    "homework:write": {"set_homework", "clear_homework"},
    "marks:read": {"list_temporary_marks", "get_student_record"},
    "marks:write": {"set_temporary_mark", "delete_temporary_mark"},
    "assessments:read": {"list_assessments"},
    "assessments:write": {"create_assessment", "update_assessment"},
    "workoffs:read": {"get_unfinished_work_report"},
    "materials:generate": {
        "generate_questions",
        "generate_handout",
        "check_student_work",
        "check_ai_authorship",
    },
    "lesson-plans:read": {"list_plan_templates"},
    "lesson-plans:write": {"register_plan_template", "generate_lesson_plan"},
}
TEACHER_AI_TOOLS = (
    TEACHER_SCOPES["materials:generate"]
    | TEACHER_SCOPES["lesson-plans:read"]
    | TEACHER_SCOPES["lesson-plans:write"]
)


def test_teacher_registry_agrees_with_the_scope_table() -> None:
    """MCP-8: every teacher tool resolves to the scope that lists it."""
    for scope, names in TEACHER_SCOPES.items():
        for name in names:
            assert tool_scope("teacher", name) == scope, name
    assert server_tools("teacher") == set().union(*TEACHER_SCOPES.values())


async def test_teacher_server_lists_its_tools_without_ai_when_unwired(
    world: World,
) -> None:
    """Without the AI port the teacher server has no generation tools."""
    token, _ = world.connector_token("teacher", *SCOPES_BY_SERVER["teacher"])

    async with world.session("teacher", token) as session:
        listed = await session.list_tools()

    assert {t.name for t in listed.tools} == server_tools("teacher") - TEACHER_AI_TOOLS


async def test_teacher_writes_are_the_marked_ones_and_deletes_destructive(
    world: World,
) -> None:
    """MCP-6: only homework, temporary marks and assessments write."""
    token, _ = world.connector_token("teacher", *SCOPES_BY_SERVER["teacher"])

    async with world.session("teacher", token) as session:
        listed = await session.list_tools()

    assert _writers(listed.tools) == {
        "set_homework",
        "clear_homework",
        "set_temporary_mark",
        "delete_temporary_mark",
        "create_assessment",
        "update_assessment",
    }
    destructive = {
        t.name
        for t in listed.tools
        if t.annotations is not None and t.annotations.destructiveHint
    }
    assert destructive == {"clear_homework", "delete_temporary_mark"}
