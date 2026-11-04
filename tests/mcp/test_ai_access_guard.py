"""MCP: a user whom Administration revoked the AI from is refused on every tool.

The guard checks the revoked scopes before the tool runs (the same cached limits the
model gateway reads), and the refusal is audited as a denial.
"""

from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.guard import ToolGuard
from app.shared.actor import Actor, Role
from app.shared.ai_access import AiAccess
from app.shared.ids import new_id
from tests.mcp.conftest import World

import pytest
from mcp.server.fastmcp.exceptions import ToolError


def _actor(world: World, user_id: UUID) -> Actor:
    return Actor(
        user_id=user_id,
        roles=frozenset({Role.STUDENT}),
        scopes=frozenset(world.all_scopes("student")),
    )


async def _call(world: World, monkeypatch: pytest.MonkeyPatch, actor: Actor) -> list:
    """Run one guarded tool as `actor`; return what the tool body recorded."""
    monkeypatch.setattr(guard_module, "_token_actor", lambda: actor)
    ran: list[str] = []
    scope = world.all_scopes("student")[0]

    async def tool() -> dict[str, object]:
        ran.append("ran")
        return {}

    wrapped = ToolGuard(world.deps(), "student").requires_scope(scope)(tool)
    try:
        await wrapped()
    except ToolError:
        pass
    return ran


async def test_a_user_with_chat_revoked_is_refused_and_the_tool_does_not_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = new_id()
    world.revoked_ai[user] = AiAccess(chat_blocked=True)

    ran = await _call(world, monkeypatch, _actor(world, user))

    assert ran == []
    denied = [e for e in world.audit.events if e.type == "mcp.denied"]
    assert denied and denied[-1].metadata["reason"] == "ai/access-revoked"


async def test_a_user_with_notebooks_revoked_is_refused_too(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = new_id()
    world.revoked_ai[user] = AiAccess(notebooks_blocked=True)

    ran = await _call(world, monkeypatch, _actor(world, user))

    assert ran == []


async def test_a_user_without_revocation_runs_the_tool(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = await _call(world, monkeypatch, _actor(world, new_id()))

    assert ran == ["ran"]
