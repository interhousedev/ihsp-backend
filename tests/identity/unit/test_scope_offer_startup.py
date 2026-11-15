"""The scheduler offers new MCP scopes at start, once; a restart sends nothing new."""

from app.interfaces.jobs.broker import STARTUP_TASKS, StartupScheduler
from app.shared.actor import Role
from app.shared.mcp_scopes import RELEASES
from tests.identity.support import World
from tests.identity.unit.test_scope_offers import _connector

import pytest
from taskiq import InMemoryBroker


async def test_scheduler_start_offers_once_and_a_restart_sends_nothing(
    auth_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy restarts the scheduler: users are asked at once, never twice."""
    monkeypatch.setattr(
        "app.modules.identity.application.offer_mcp_scopes.RELEASES", RELEASES[:1]
    )
    user = await auth_world.add_user(roles={Role.STUDENT}, login="s.start")
    made = _connector(user)
    auth_world.store.connectors[made.id] = made

    results: list[int] = []
    broker = InMemoryBroker()

    @broker.task(task_name="identity.offer_mcp_scopes")
    async def offer() -> int:
        made_now: int = await auth_world.auth.offer_mcp_scopes.execute()
        results.append(made_now)
        return made_now

    assert STARTUP_TASKS == ("identity.offer_mcp_scopes",)
    for _ in range(2):  # first start, then a restart
        scheduler = StartupScheduler(broker=broker, sources=[])
        await scheduler.startup()
        await broker.wait_all()

    assert results == [1, 0]
    assert len(auth_world.store.notifications) == 1
    assert len(auth_world.store.scope_offers) == 1
