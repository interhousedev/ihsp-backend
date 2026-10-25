"""MCP-5, MCP-7, UF-MCP-03: scopes are checked on every call; denials are audited."""

from app.interfaces.mcp.constants import CALLS_PER_MINUTE
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of


async def test_granted_scope_runs_the_tool(world: World) -> None:
    """UF-MCP-03: a connector with schedule:read can call get_schedule."""
    token, actor = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule")

    assert data_of(result)["lessons"] == []
    assert world.schedule.calls[0][1][0] == actor.user_id
    assert world.audit.events == []


async def test_missing_scope_is_insufficient_scope_and_audited(world: World) -> None:
    """UF-MCP-03 2a, MCP-7: the error names the scope and the denial is logged."""
    token, actor = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        result = await call(session, "get_marks")

    assert result.isError
    assert "insufficient_scope" in text_of(result)
    assert "marks:read" in text_of(result)
    assert world.marks.calls == []
    [event] = world.audit.of_type("mcp.denied")
    assert event.user_id == actor.user_id
    assert event.metadata is not None
    assert event.metadata["tool"] == "get_marks"
    assert event.metadata["scope"] == "marks:read"
    assert event.metadata["server"] == "student"
    assert event.metadata["connector_id"] == str(actor.connector_id)
    assert event.metadata["reason"] == "mcp/insufficient-scope"


async def test_the_61st_call_in_a_minute_is_refused(world: World) -> None:
    """MCP-7: 60 calls per minute per connector."""
    token, _ = world.connector_token("student", "schedule:read")

    async with world.session("student", token) as session:
        for _ in range(CALLS_PER_MINUTE):
            assert not (await call(session, "get_schedule")).isError
        refused = await call(session, "get_schedule")

    assert refused.isError
    assert "Too many calls" in text_of(refused)
    assert len(world.schedule.calls) == CALLS_PER_MINUTE
    [event] = world.audit.of_type("mcp.denied")
    assert event.metadata is not None
    assert event.metadata["reason"] == "mcp/rate-limited"


async def test_rate_limit_is_per_connector(world: World) -> None:
    """MCP-7: another connector of the same user has its own counter."""
    first, _ = world.connector_token("student", "schedule:read")
    second, _ = world.connector_token("student", "schedule:read")

    async with world.serve() as server:
        async with server.session("student", first) as session:
            for _ in range(CALLS_PER_MINUTE + 1):
                await call(session, "get_schedule")
        async with server.session("student", second) as session:
            result = await call(session, "get_schedule")

    assert not result.isError


async def test_unexpected_failure_hides_internals_and_gives_an_error_id(
    world: World,
) -> None:
    """A bug in a use case never leaks its message to the AI client."""
    token, _ = world.connector_token("student", "schedule:read")

    async def broken(*args: object) -> None:
        raise RuntimeError("secret sql text")

    world.marks.subjects_summary = broken  # type: ignore[method-assign,assignment]

    async with world.session("student", token) as session:
        result = await call(session, "get_my_subjects")

    assert result.isError
    assert "secret sql text" not in text_of(result)
    assert "Report error" in text_of(result)
