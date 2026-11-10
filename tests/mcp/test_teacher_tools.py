"""Teachers MCP server: role gate, own groups only, homework, optional AI tools."""

from uuid import UUID

from app.interfaces.mcp.constants import SCOPES_BY_SERVER
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call

SCOPES = SCOPES_BY_SERVER["teacher"]
AI_TOOLS = {
    "generate_questions",
    "generate_handout",
    "check_student_work",
    "check_ai_authorship",
    "list_plan_templates",
    "register_plan_template",
    "generate_lesson_plan",
}


async def _tool_names(world: World) -> set[str]:
    token, _ = world.connector_token("teacher", *SCOPES)
    async with world.session("teacher", token) as session:
        return {tool.name for tool in (await session.list_tools()).tools}


async def test_student_cannot_use_the_teacher_server(world: World) -> None:
    """Role gate: a student token is refused."""
    token, _ = world.connector_token("teacher", *SCOPES, roles=(Role.STUDENT,))

    async with world.serve() as server:
        response = await server.raw.post(
            "/mcp/teacher/", json={}, headers={"authorization": f"Bearer {token}"}
        )

    assert response.status_code in (401, 403)
    assert world.teacher_tools.calls == []


async def test_roster_of_a_foreign_group_is_refused(world: World) -> None:
    """Own group only: the use case's refusal reaches the client."""
    own, foreign = new_id(), new_id()
    world.teacher_tools.own_group_ids = {own}
    token, _ = world.connector_token("teacher", *SCOPES)

    async with world.session("teacher", token) as session:
        ok = await call(session, "get_group_roster", group_id=str(own))
        denied = await call(session, "get_group_roster", group_id=str(foreign))

    assert not ok.isError
    assert denied.isError


async def test_set_homework_reaches_the_adapter_with_the_actor(world: World) -> None:
    """The actor comes from the token; the text and date are passed through."""
    lesson_id = new_id()
    token, actor = world.connector_token("teacher", *SCOPES)

    async with world.session("teacher", token) as session:
        result = await call(
            session,
            "set_homework",
            lesson_id=str(lesson_id),
            text="Read p. 5",
            due_date="2030-01-10",
        )

    assert not result.isError
    name, args = world.teacher_tools.calls[-1]
    assert name == "set_homework"
    assert args[0].user_id == actor.user_id
    assert UUID(str(args[1])) == lesson_id
    assert args[2] == "Read p. 5"


async def test_ai_tools_are_absent_without_the_backend(world: World) -> None:
    """`teacher_ai` is optional: no AI tools are listed when it is not set."""
    names = await _tool_names(world)

    assert "set_homework" in names
    assert not AI_TOOLS & names
