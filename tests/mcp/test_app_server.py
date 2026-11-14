"""The universal `app` server: prefixed tools, namespaced scopes, per-call roles."""

from app.interfaces.mcp.constants import ALLOWED_ROLES_BY_SERVER, SCOPES_BY_SERVER
from app.shared.actor import Role
from app.shared.mcp_scopes import SCOPE_CATALOG
from tests.mcp.conftest import World
from tests.mcp.helpers import call, text_of

SCOPES = SCOPES_BY_SERVER["app"]


async def _names(world: World, roles: tuple[Role, ...]) -> set[str]:
    token, _ = world.connector_token("app", *SCOPES, roles=roles)
    async with world.session("app", token) as session:
        return {tool.name for tool in (await session.list_tools()).tools}


def test_catalog_is_derived_from_the_three_sources() -> None:
    """Scopes are `<source>:<scope>` and tools `<source>_<tool>`, nothing else."""
    assert {info.scope.split(":")[0] for info in SCOPE_CATALOG["app"]} == {
        "student",
        "teacher",
        "lms",
    }
    for info in SCOPE_CATALOG["app"]:
        source = info.scope.split(":")[0]
        assert all(tool.startswith(f"{source}_") for tool in info.tools)
    assert ALLOWED_ROLES_BY_SERVER["app"] == (
        ALLOWED_ROLES_BY_SERVER["student"]
        | ALLOWED_ROLES_BY_SERVER["teacher"]
        | ALLOWED_ROLES_BY_SERVER["lms"]
    )
    assert Role.ADMIN in ALLOWED_ROLES_BY_SERVER["app"]


async def test_a_student_sees_no_teacher_tools(world: World) -> None:
    """tools/list is filtered by the roles of each source server."""
    names = await _names(world, (Role.STUDENT,))

    assert "student_get_marks" in names
    assert not {name for name in names if name.startswith("teacher_")}
    assert not {name for name in names if not name.startswith(("student_", "lms_"))}


async def test_a_teacher_sees_teacher_and_lms_tools_but_no_student_tools(
    world: World,
) -> None:
    """A teacher role allows the teacher and LMS sets only."""
    names = await _names(world, (Role.TEACHER,))

    assert "teacher_get_today" in names
    assert any(name.startswith("lms_") for name in names)
    assert not {name for name in names if name.startswith("student_")}


async def test_a_teacher_tool_is_refused_for_a_student_even_with_the_scope(
    world: World,
) -> None:
    """The roles are checked on every call against the source server."""
    token, actor = world.connector_token(
        "app", "teacher:schedule:read", roles=(Role.STUDENT,)
    )

    async with world.session("app", token) as session:
        result = await call(session, "teacher_get_today")

    assert result.isError
    assert "insufficient_scope" in text_of(result)
    assert world.teacher_tools.calls == []
    [event] = world.audit.of_type("mcp.denied")
    assert event.metadata is not None
    assert event.metadata["server"] == "app"
    assert event.user_id == actor.user_id


async def test_the_namespaced_scope_is_required(world: World) -> None:
    """`marks:read` without its source prefix does not open `student_get_marks`."""
    token, _ = world.connector_token("app", "marks:read", "teacher:marks:read")

    async with world.session("app", token) as session:
        result = await call(session, "student_get_marks")

    assert result.isError
    assert "insufficient_scope" in text_of(result)
    assert "student:marks:read" in text_of(result)
    assert world.marks.calls == []


async def test_a_granted_namespaced_scope_runs_and_is_logged_as_app(
    world: World,
) -> None:
    """The call log names server `app` and the prefixed tool."""
    token, _ = world.connector_token("app", "student:schedule:read")

    async with world.session("app", token) as session:
        result = await call(session, "student_get_schedule")

    assert not result.isError, text_of(result)
    [row] = world.call_log.records
    assert row.server == "app"
    assert row.tool == "student_get_schedule"
