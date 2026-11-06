"""MCP-5, MCP-7, UF-MCP-03: scopes are checked on every call; denials are audited."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.constants import (
    CALLS_PER_MINUTE,
    USER_CALLS_PER_MINUTE,
    ServerName,
    ToolLimit,
)
from app.interfaces.mcp.guard import ToolGuard
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

import pytest
from mcp.server.fastmcp.exceptions import ToolError


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


async def test_many_connectors_of_one_user_share_a_user_limit(world: World) -> None:
    """MCP-7: N connectors do not give N times the budget."""
    user = new_id()
    first, _ = world.connector_token("student", "schedule:read", user_id=user)
    second, _ = world.connector_token("student", "schedule:read", user_id=user)
    third, _ = world.connector_token("student", "schedule:read", user_id=user)

    async with world.serve() as server:
        for token in (first, second):
            async with server.session("student", token) as session:
                for _ in range(CALLS_PER_MINUTE):
                    assert not (await call(session, "get_schedule")).isError
        async with server.session("student", third) as session:
            refused = await call(session, "get_schedule")

    assert USER_CALLS_PER_MINUTE == 2 * CALLS_PER_MINUTE
    assert refused.isError
    assert "Too many calls" in text_of(refused)


async def _guarded_tool(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    actor: Actor,
    *,
    scope: str = "marks:read",
    limit: ToolLimit | None = None,
    overlay: frozenset[str] | None = None,
    server: ServerName = "student",
) -> Callable[[], Awaitable[dict[str, Any]]]:
    monkeypatch.setattr(guard_module, "_token_actor", lambda: actor)
    world.overlay.extra = overlay or frozenset()

    async def tool() -> dict[str, Any]:
        return {"ok": True}

    guard = ToolGuard(world.deps(), server)
    return guard.requires_scope(scope, limit=limit)(tool)


def _actor(*scopes: str, client_id: str | None = None) -> Actor:
    return Actor(
        user_id=new_id(),
        roles=frozenset({Role.STUDENT}),
        connector_id=new_id(),
        client_id=client_id,
        scopes=frozenset(scopes),
    )


async def test_a_tool_cost_class_is_counted_per_user(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limit class: another class or another user is not touched."""
    tool = await _guarded_tool(
        world, monkeypatch, _actor("marks:read"), limit=ToolLimit("test", 2, 60)
    )

    await tool()
    await tool()
    with pytest.raises(ToolError, match="Too many calls"):
        await tool()

    other = await _guarded_tool(
        world, monkeypatch, _actor("marks:read"), limit=ToolLimit("test", 2, 60)
    )
    assert await other() == {"ok": True}


async def test_a_call_without_the_scope_does_not_spend_the_tool_class(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limit class: counted after the scope check."""
    actor = _actor("schedule:read")
    tool = await _guarded_tool(
        world, monkeypatch, actor, limit=ToolLimit("test", 1, 60)
    )

    with pytest.raises(ToolError, match="insufficient_scope"):
        await tool()

    assert await world.redis.get(f"rl:mcp:test:{actor.user_id}") is None


async def test_oauth_token_gains_scopes_from_the_connector_overlay(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: Hydra keeps the old `scp`, the grant is read from the connector."""
    actor = _actor(client_id="client")
    tool = await _guarded_tool(
        world, monkeypatch, actor, overlay=frozenset({"marks:read"})
    )

    assert await tool() == {"ok": True}
    assert world.overlay.asked == [actor.connector_id]


async def test_connector_token_ignores_the_overlay(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: a connector token already carries its live scopes."""
    tool = await _guarded_tool(
        world, monkeypatch, _actor(), overlay=frozenset({"marks:read"})
    )

    with pytest.raises(ToolError, match="insufficient_scope"):
        await tool()


async def test_overlay_cannot_add_a_scope_of_another_server(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: the grant is re-validated against this server's catalog."""
    tool = await _guarded_tool(
        world,
        monkeypatch,
        _actor(client_id="client"),
        scope="people:read",
        overlay=frozenset({"people:read"}),
    )

    with pytest.raises(ToolError, match="insufficient_scope"):
        await tool()


async def test_administration_server_never_reads_the_overlay(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: the OTP step-up of Administration connectors cannot be bypassed."""
    actor = _actor(client_id="client")
    tool = await _guarded_tool(
        world,
        monkeypatch,
        actor,
        scope="people:read",
        overlay=frozenset({"people:read"}),
        server="admin",
    )

    with pytest.raises(ToolError, match="insufficient_scope"):
        await tool()
    assert world.overlay.asked == []


async def test_a_failing_overlay_grants_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: fail closed."""
    tool = await _guarded_tool(world, monkeypatch, _actor(client_id="client"))
    world.overlay.fail = True

    with pytest.raises(ToolError, match="insufficient_scope"):
        await tool()


async def test_has_scope_checks_a_second_scope_with_the_overlay(world: World) -> None:
    """Tools with a second scope (flashcards:delete, files:read.all) use this."""
    guard = ToolGuard(world.deps(), "student")
    world.overlay.extra = frozenset({"files:read.all"})

    assert await guard.has_scope(_actor("marks:read"), "marks:read")
    assert not await guard.has_scope(_actor(), "files:read.all")
    assert await guard.has_scope(_actor(client_id="c"), "files:read.all")


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
