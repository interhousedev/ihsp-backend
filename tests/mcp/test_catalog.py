"""The tool catalog: a small tools/list, search, describe and guarded dispatch."""

from app.interfaces.mcp.catalog import META_TOOLS
from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from app.shared.actor import Role
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of, tool_names

APP_SCOPES = SCOPES_BY_SERVER["app"]


async def test_a_student_lists_only_meta_and_pinned_tools_on_app(
    world: World,
) -> None:
    """tools/list is small and holds no tool of another role."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.STUDENT,))

    async with world.session("app", token) as session:
        names = await tool_names(session)

    assert names == META_TOOLS | {
        "student_find_feature",
        "student_get_schedule",
        "student_get_homework",
        "student_upload_file",
        "lms_list_courses",
    }


async def test_role_servers_list_a_short_set(world: World) -> None:
    """The student, teacher and LMS servers list meta and pinned tools only."""
    for server, roles, limit in (
        ("student", (Role.STUDENT,), 5),
        ("teacher", (Role.TEACHER,), 4),
        ("lms", (Role.TEACHER,), 3),
    ):
        token, _ = world.connector_token(server, *SCOPES_BY_SERVER[server], roles=roles)
        async with world.session(server, token) as session:
            names = await tool_names(session)
        assert META_TOOLS <= names
        assert len(names - META_TOOLS) == limit, server


async def test_search_as_a_student_finds_student_tools_never_teacher_tools(
    world: World,
) -> None:
    """search_tools only shows tools the caller's roles allow."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.STUDENT,))

    async with world.session("app", token) as session:
        result = await call(session, "search_tools", query="homework")

    names = [item["name"] for item in data_of(result)["items"]]
    assert "student_get_homework" in names
    assert not [name for name in names if name.startswith("teacher_")]
    assert not META_TOOLS & set(names)


async def test_search_as_a_teacher_finds_teacher_homework_tools(world: World) -> None:
    """A teacher finds the teacher set and no student tool."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.TEACHER,))

    async with world.session("app", token) as session:
        result = await call(session, "search_tools", query="homework", limit=30)

    names = [item["name"] for item in data_of(result)["items"]]
    assert any(name.startswith("teacher_") for name in names)
    assert not [name for name in names if name.startswith("student_")]


async def test_describe_tool_returns_schema_and_hides_other_roles(
    world: World,
) -> None:
    """describe_tool gives the input schema; another role's tool is unknown."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.STUDENT,))

    async with world.session("app", token) as session:
        found = await call(session, "describe_tool", name="student_get_homework")
        hidden = await call(session, "describe_tool", name="teacher_get_today")

    data = data_of(found)
    assert data["read_only"] is True
    assert data["input_schema"]["type"] == "object"
    assert hidden.isError
    assert "Unknown tool" in text_of(hidden)


async def test_run_read_tool_logs_the_inner_tool_name(world: World) -> None:
    """The guard of the real tool runs and logs under its own name."""
    token, _ = world.connector_token("app", "student:schedule:read")

    async with world.session("app", token) as session:
        result = await call(
            session, "run_read_tool", name="student_get_schedule", arguments={}
        )

    assert not result.isError, text_of(result)
    [row] = world.call_log.records
    assert row.server == "app"
    assert row.tool == "student_get_schedule"


async def test_run_read_tool_refuses_a_write_tool(world: World) -> None:
    """A tool that is not read-only is refused before it runs."""
    token, _ = world.connector_token(
        "app", "student:flashcards:write", roles=(Role.STUDENT,)
    )

    async with world.session("app", token) as session:
        result = await call(
            session,
            "run_read_tool",
            name="student_create_flashcard_set",
            arguments={"title": "x", "cards": []},
        )

    assert result.isError
    assert "run_write_tool" in text_of(result)
    assert world.flashcards.created == []
    assert world.call_log.records == []


async def test_run_write_tool_is_refused_by_the_guard_for_a_foreign_role(
    world: World,
) -> None:
    """The role re-check of the real tool still applies through run_write_tool."""
    token, _ = world.connector_token(
        "app", "teacher:schedule:read", roles=(Role.STUDENT,)
    )

    async with world.session("app", token) as session:
        result = await call(
            session, "run_write_tool", name="teacher_get_today", arguments={}
        )

    assert result.isError
    assert world.teacher_tools.calls == []


async def test_a_hidden_tool_is_still_callable_by_name(world: World) -> None:
    """A client that cached a tool name keeps working."""
    token, _ = world.connector_token("student", "marks:read")

    async with world.session("student", token) as session:
        result = await call(session, "get_marks")

    assert not result.isError, text_of(result)
    [row] = world.call_log.records
    assert row.tool == "get_marks"


async def test_meta_tools_cannot_run_each_other(world: World) -> None:
    """run_read_tool does not dispatch to a meta tool."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.STUDENT,))

    async with world.session("app", token) as session:
        result = await call(
            session, "run_read_tool", name="search_tools", arguments={"query": "x"}
        )

    assert result.isError


async def test_upload_tools_are_pinned_automatically_per_role(world: World) -> None:
    """A tool with `openai/fileParams` meta is listed directly, for its role only."""
    token, _ = world.connector_token("app", *APP_SCOPES, roles=(Role.TEACHER,))

    async with world.session("app", token) as session:
        listed = (await session.list_tools()).tools

    [upload] = [tool for tool in listed if tool.name.endswith("upload_file")]
    assert upload.name == "teacher_upload_file"
    assert upload.meta is not None and upload.meta["openai/fileParams"] == ["file"]
