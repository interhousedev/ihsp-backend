"""MCP-1, MCP-6, MCP-8: the exact tools of each server and their scopes."""

import re
from typing import Any

from app.interfaces.mcp.constants import ADMIN_READ_TOOLS, SCOPES_BY_SERVER, ServerName
from tests.mcp.conftest import World
from tests.mcp.helpers import call, text_of

import pytest
from mcp.types import Tool

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
    "list_courses": ("courses:read", {}),
    "get_course": ("courses:read", {"course_id": COURSE}),
    "get_step": ("courses:read", {"step_id": STEP}),
    "list_pending_changes": ("courses:read", {"course_id": COURSE}),
    "list_versions": ("courses:read", {"course_id": COURSE}),
    "list_attempts": ("courses:read", {"course_id": COURSE}),
    "create_section": ("courses:draft", {"course_id": COURSE, "title": "t"}),
    "create_step": (
        "courses:draft",
        {"course_id": COURSE, "section_id": "s", "title": "t"},
    ),
    "add_text_block": ("courses:draft", {"step_id": STEP, "markdown": "m"}),
    "add_test_block": ("courses:draft", {"step_id": STEP}),
    "add_question": (
        "courses:draft",
        {"step_id": STEP, "block_id": "b", "question": QUESTION},
    ),
    "add_flashcards_block": ("courses:draft", {"step_id": STEP, "cards": CARDS}),
}
ADMIN_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "search_users": ("people:read", {"query": "x"}),
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


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_server_offers_exactly_the_tools_of_mcp_8(
    world: World, server: ServerName
) -> None:
    """MCP-8: the tools of each server, nothing else."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])

    async with world.session(server, token) as session:
        listed = await session.list_tools()

    assert {tool.name for tool in listed.tools} == set(CATALOG[server])


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
async def test_no_server_has_a_delete_or_publish_tool(
    world: World, server: ServerName
) -> None:
    """MCP-6, UF-LMS-16 2a: nothing deletes, edits existing content or publishes."""
    token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server])

    async with world.session(server, token) as session:
        listed = await session.list_tools()

    names = [tool.name for tool in listed.tools]
    assert not [name for name in names if FORBIDDEN_VERBS.search(name)]
    assert "create_course" not in names


async def test_lms_server_only_adds_to_drafts(world: World) -> None:
    """MCP-6: the LMS write tools are the six additive ones."""
    token, _ = world.connector_token("lms", *SCOPES_BY_SERVER["lms"])

    async with world.session("lms", token) as session:
        listed = await session.list_tools()

    writers = _writers(listed.tools)
    assert writers == {
        "create_section",
        "create_step",
        "add_text_block",
        "add_test_block",
        "add_question",
        "add_flashcards_block",
    }


async def test_students_server_flash_cards_can_be_created_and_edited_only(
    world: World,
) -> None:
    """MCP-6: the Students write tools are create, add and update."""
    token, _ = world.connector_token("student", *SCOPES_BY_SERVER["student"])

    async with world.session("student", token) as session:
        listed = await session.list_tools()

    writers = _writers(listed.tools)
    assert writers == {"create_flashcard_set", "add_flashcards", "update_flashcard"}


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
