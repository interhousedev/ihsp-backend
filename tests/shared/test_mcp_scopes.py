"""MCP-8: one registry of MCP scopes; releases are append-only."""

from app.interfaces.mcp import constants
from app.modules.identity.domain import scopes as identity_scopes
from app.shared import mcp_scopes
from app.shared.lms_scopes import LEGACY_ALIASES

import pytest

# Frozen: add a new id here with a new release, never change or remove one.
RELEASE_IDS = ("2026-11-mcp-1",)


def test_interface_and_identity_read_the_same_tables() -> None:
    """MCP-8: the two old public names are the registry, so they cannot drift."""
    assert identity_scopes.SCOPE_CATALOG is mcp_scopes.SCOPE_CATALOG
    assert constants.SCOPES_BY_SERVER == {
        server: tuple(info.scope for info in infos)
        for server, infos in mcp_scopes.SCOPE_CATALOG.items()
    }


def test_releases_are_append_only() -> None:
    """A7: an id already offered to users keeps its place."""
    assert tuple(release.id for release in mcp_scopes.RELEASES) == RELEASE_IDS


@pytest.mark.parametrize("release", mcp_scopes.RELEASES, ids=lambda r: r.id)
def test_a_release_lists_only_scopes_of_its_one_server(
    release: mcp_scopes.ScopeRelease,
) -> None:
    """A7: a release cannot widen another server."""
    known = {info.scope for info in mcp_scopes.SCOPE_CATALOG[release.server]}

    assert release.scopes
    assert set(release.scopes) <= known
    assert release.summary_key.startswith("mcp-")


def test_every_scope_of_a_release_says_it_came_with_that_release() -> None:
    """A7: `since` and the release tables agree."""
    for release in mcp_scopes.RELEASES:
        for scope in release.scopes:
            assert mcp_scopes.scope_info(release.server, scope).since == release.id


def test_no_release_offers_the_administration_server() -> None:
    """D7: its connectors need an OTP step-up that a button would bypass."""
    assert "admin" not in mcp_scopes.OFFERABLE_SERVERS
    assert all(release.server != "admin" for release in mcp_scopes.RELEASES)


def test_student_scope_names_do_not_collide_with_legacy_lms_aliases() -> None:
    """A legacy alias expands to LMS authoring scopes; a learner must not hold one."""
    names = {info.scope for info in mcp_scopes.SCOPE_CATALOG["student"]}

    assert not names & set(LEGACY_ALIASES)


@pytest.mark.parametrize("server", ["student", "lms", "admin"])
def test_a_tool_belongs_to_one_scope(server: str) -> None:
    """MCP-8: the scope a tool needs is not ambiguous."""
    tools = [t for info in mcp_scopes.SCOPE_CATALOG[server] for t in info.tools]

    assert len(tools) == len(set(tools))


def test_widening_scope_names_existing_tools_only() -> None:
    """B4: `files:read.all` adds no tool; it widens three."""
    info = mcp_scopes.scope_info("student", "files:read.all")

    assert info.tools == ()
    assert set(info.widens) == {"list_files", "search_files", "read_file"}
    assert set(info.widens) <= mcp_scopes.server_tools("student")


def test_every_planned_tool_is_named() -> None:
    """WP1: the other packages find their tools in the registry."""
    expected = {
        "refresh_my_marks": "sync:run",
        "get_sync_status": "sync:run",
        "get_my_teachers": "teachers:read",
        "get_teacher_timetable": "teachers:read",
        "search_knowledge": "knowledge:read",
        "delete_flashcards": "flashcards:delete",
        "list_tests": "tests:read",
        "get_test": "tests:read",
        "create_test": "tests:write",
        "batch_edit_test_questions": "tests:write",
        "list_notebooks": "notebooks:read",
        "generate_notebook_output": "notebooks:write",
        "search_library": "library:read",
        "get_course_media_link": "learning:read",
        "update_flashcard_set": "flashcards:write",
        "batch_edit_flashcards": "flashcards:write",
        "get_lesson_detail": "materials:read",
        "get_gpa": "marks:read",
        "upload_file": "files:write",
        "submit_homework": "homework:submit",
        "withdraw_homework_submission": "homework:submit",
    }

    for tool, scope in expected.items():
        assert mcp_scopes.tool_scope("student", tool) == scope
