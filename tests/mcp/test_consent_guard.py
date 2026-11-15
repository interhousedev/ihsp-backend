"""MCP: a user who has not accepted the legal documents is refused on every tool."""

from dataclasses import replace
from uuid import UUID

from app.interfaces.mcp import guard as guard_module
from app.interfaces.mcp.guard import ToolGuard
from app.modules.legal.domain.errors import LegalAcceptanceRequiredError
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.mcp.conftest import World

import pytest
from mcp.server.fastmcp.exceptions import ToolError


class Gate:
    """A consent gate that refuses one user."""

    def __init__(self, refused: UUID) -> None:
        """Remember who is refused."""
        self.refused = refused

    async def execute(self, user_id: UUID) -> None:
        """Refuse the user, let the others pass."""
        if user_id == self.refused:
            raise LegalAcceptanceRequiredError(params={"kinds": "privacy"})


async def _call(
    world: World, monkeypatch: pytest.MonkeyPatch, actor: Actor, gate: Gate
) -> list[str]:
    monkeypatch.setattr(guard_module, "_token_actor", lambda: actor)
    ran: list[str] = []
    scope = world.all_scopes("student")[0]

    async def tool() -> dict[str, object]:
        ran.append("ran")
        return {}

    deps = replace(world.deps(), consent=gate)
    wrapped = ToolGuard(deps, "student").requires_scope(scope)(tool)
    try:
        await wrapped()
    except ToolError:
        pass
    return ran


async def test_unaccepted_user_is_refused_and_the_tool_does_not_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = new_id()
    actor = Actor(
        user_id=user,
        roles=frozenset({Role.STUDENT}),
        scopes=frozenset(world.all_scopes("student")),
    )

    assert await _call(world, monkeypatch, actor, Gate(user)) == []
    denied = [e for e in world.audit.events if e.type == "mcp.denied"]
    assert denied and (denied[-1].metadata or {})["reason"] == (
        "legal/acceptance-required"
    )


async def test_accepted_user_runs_the_tool(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = Actor(
        user_id=new_id(),
        roles=frozenset({Role.STUDENT}),
        scopes=frozenset(world.all_scopes("student")),
    )

    assert await _call(world, monkeypatch, actor, Gate(new_id())) == ["ran"]
