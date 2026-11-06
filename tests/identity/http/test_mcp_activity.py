"""B1: the activity routes: scoped to the actor, admin-only reads are audited."""

from typing import Any
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.ids import new_id
from tests.identity.http.conftest import Api
from tests.identity.support import World


async def _log(world: World, user_id: UUID, **fields: Any) -> None:
    base: dict[str, Any] = {
        "user_id": user_id,
        "connector_id": None,
        "client_id": None,
        "server": "student",
        "tool": "get_marks",
        "scope": "marks:read",
        "read_only": True,
        "outcome": "ok",
        "error_code": None,
        "error_id": None,
        "duration_ms": 3,
        "arguments": {"limit": 5},
        "result_summary": {"count": 2},
        "ip": "10.0.0.1",
    }
    async with world.uow() as uow:
        await uow.mcp_calls.add(McpCallRecord(**{**base, **fields}))
        await uow.commit()


async def test_a_user_sees_only_their_own_calls(api: Api) -> None:
    """B1: another person's connector id finds nothing (no IDOR)."""
    me = await api.world.add_user(login="me.one")
    other = await api.world.add_user(login="other.one")
    connector = new_id()
    await _log(api.world, me.id, tool="mine")
    await _log(api.world, other.id, tool="theirs", connector_id=connector)
    api.login_as(me)

    everything = await api.client.get("/v1/id/me/connectors/activity")
    foreign = await api.client.get(
        "/v1/id/me/connectors/activity", params={"connector_id": str(connector)}
    )

    assert everything.status_code == 200
    body = everything.json()
    assert [item["tool"] for item in body["items"]] == ["mine"]
    assert body["items"][0]["arguments"] == {"limit": 5}
    assert "user_id" not in body["items"][0]
    assert foreign.json()["items"] == []


async def test_activity_needs_a_sign_in(api: Api) -> None:
    """B1: no actor, no log."""
    response = await api.client.get("/v1/id/me/connectors/activity")
    assert response.status_code == 401


async def test_a_bad_filter_is_refused(api: Api) -> None:
    """B1: unknown outcome and broken cursor are 422."""
    api.login_as(await api.world.add_user(login="me.one"))

    bad_outcome = await api.client.get(
        "/v1/id/me/connectors/activity", params={"outcome": "nope"}
    )
    bad_cursor = await api.client.get(
        "/v1/id/me/connectors/activity", params={"cursor": "!!!"}
    )

    assert bad_outcome.status_code == 422
    assert bad_cursor.status_code == 422


async def test_admin_routes_refuse_everyone_else(api: Api) -> None:
    """B1: `require_roles(ADMIN)`, a teacher and a student are refused."""
    for role in (Role.STUDENT, Role.TEACHER):
        api.login_as(await api.world.add_user(login=f"u.{role}", roles={role}))
        for path in ("/v1/admin/mcp/activity", "/v1/admin/mcp/activity/summary"):
            assert (await api.client.get(path)).status_code == 403


async def test_admin_reads_with_filters_and_each_read_is_audited(api: Api) -> None:
    """B1: every read writes `mcp.activity_viewed` with its filter."""
    user = await api.world.add_user(login="me.one")
    await _log(api.world, user.id, tool="a", outcome="error")
    await _log(api.world, user.id, tool="b")
    actor = await api.admin()

    response = await api.client.get(
        "/v1/admin/mcp/activity",
        params={"user_id": str(user.id), "outcome": "error"},
    )

    body = response.json()
    assert [item["tool"] for item in body["items"]] == ["a"]
    assert body["items"][0]["user_id"] == str(user.id)
    [event] = [a for a in api.world.store.audits if a.type == "mcp.activity_viewed"]
    assert event.user_id == actor.user_id
    assert event.metadata is not None
    assert event.metadata["filter"] == {"user_id": str(user.id), "outcome": "error"}


async def test_admin_summary_counts_calls_and_errors_per_tool(api: Api) -> None:
    """B1: calls and errors per tool, audited too."""
    user = await api.world.add_user(login="me.one")
    await _log(api.world, user.id, tool="a", outcome="denied")
    await _log(api.world, user.id, tool="a")
    await _log(api.world, user.id, tool="b")
    await api.admin()

    response = await api.client.get("/v1/admin/mcp/activity/summary")

    assert response.json()["items"] == [
        {"server": "student", "tool": "a", "calls": 2, "errors": 1},
        {"server": "student", "tool": "b", "calls": 1, "errors": 0},
    ]
    assert "mcp.activity_viewed" in api.world.store.audit_types()
