"""MCP-1, ADM: the Administration server forwards read-only tools and audits calls."""

from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.constants import ADMIN_READ_TOOLS, SCOPES_BY_SERVER
from app.interfaces.mcp.errors import McpToolNotAllowedError
from app.interfaces.mcp.guard import ToolGuard, clip_for_audit
from app.interfaces.mcp.toolkit import ToolKit
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

import pytest
from mcp.server.fastmcp import FastMCP

ALL = SCOPES_BY_SERVER["admin"]
GROUP = UUID(int=0x61)
USER = UUID(int=0x62)


async def test_search_users_reaches_the_backend_as_the_caller(world: World) -> None:
    """AI-6 tool names: the backend gets the tool, JSON arguments and the actor."""
    token, actor = world.connector_token("admin", *ALL)

    async with world.session("admin", token) as session:
        result = await call(
            session, "search_users", query="ali", roles=["student"], limit=5
        )

    assert data_of(result)["tool"] == "search_users"
    [(tool, arguments, caller)] = world.admin_tools.calls
    assert tool == "search_users"
    assert arguments == {"query": "ali", "roles": ["student"], "limit": 5}
    assert caller == actor


async def test_ids_and_dates_are_sent_as_json_strings_and_none_is_dropped(
    world: World,
) -> None:
    """The adapter sees the same JSON the Administration assistant sends."""
    token, _ = world.connector_token("admin", *ALL)

    async with world.session("admin", token) as session:
        await call(
            session,
            "list_lessons",
            date_from="2026-10-01",
            date_to="2026-10-03",
            group_id=str(GROUP),
        )
        await call(session, "get_student", user_id=str(USER))

    lessons, student = world.admin_tools.calls
    assert lessons[1] == {
        "date_from": "2026-10-01",
        "date_to": "2026-10-03",
        "group_id": str(GROUP),
    }
    assert student[1] == {"user_id": str(USER)}


async def test_every_admin_call_is_audited_as_mcp_call(world: World) -> None:
    """UF-MCP-03, GEN-6: Administration MCP calls are written to the audit log."""
    token, actor = world.connector_token("admin", *ALL)

    async with world.session("admin", token) as session:
        await call(session, "get_student", user_id=str(USER))
        await call(session, "sync_status")

    first, second = world.audit.of_type("mcp.call")
    assert first.user_id == actor.user_id
    assert first.actor_id == actor.user_id
    assert first.metadata is not None
    assert first.metadata["server"] == "admin"
    assert first.metadata["tool"] == "get_student"
    assert first.metadata["arguments"] == {"user_id": str(USER)}
    assert first.metadata["connector_id"] == str(actor.connector_id)
    assert second.metadata is not None
    assert second.metadata["tool"] == "sync_status"


async def test_missing_attendance_defaults_to_the_last_week(world: World) -> None:
    """MCP-8: finished lessons without attendance, 7 days up to today."""
    token, _ = world.connector_token("admin", *ALL)

    async with world.session("admin", token) as session:
        await call(session, "missing_attendance")

    [(_, arguments, _)] = world.admin_tools.calls
    assert arguments == {"date_from": "2026-09-30", "date_to": "2026-10-06"}


async def test_denied_admin_call_is_audited_as_denied_not_as_call(world: World) -> None:
    """MCP-7: a call without its scope never reaches the backend."""
    token, _ = world.connector_token("admin", "people:read")

    async with world.session("admin", token) as session:
        result = await call(session, "audit_log")

    assert result.isError
    assert "audit:read" in text_of(result)
    assert world.admin_tools.calls == []
    assert world.audit.of_type("mcp.call") == []
    assert len(world.audit.of_type("mcp.denied")) == 1


def test_audit_arguments_are_shortened() -> None:
    """Audit rows stay small: long text and long lists are clipped."""
    clipped = clip_for_audit({"query": "x" * 500, "ids": list(range(100)), "n": 3})

    assert clipped["query"] == "x" * 200
    assert clipped["ids"] == list(range(20))
    assert clipped["n"] == 3


async def test_only_read_tools_can_be_forwarded(world: World) -> None:
    """MCP-1: a write tool name is refused before it reaches AdminToolBackend."""
    server = FastMCP("test")
    kit = ToolKit(mcp=server, deps=world.deps(), guard=ToolGuard(world.deps(), "admin"))

    with pytest.raises(McpToolNotAllowedError):
        await call_admin_tool(kit, "create_group", {"name": "x"})

    assert world.admin_tools.calls == []
    assert "create_group" not in ADMIN_READ_TOOLS
    assert not [
        name
        for name in ADMIN_READ_TOOLS
        if name.startswith(("create", "update", "delete"))
    ]


async def test_all_twelve_tools_forward_their_own_name(world: World) -> None:
    """MCP-8: each tool forwards exactly its own name."""
    token, _ = world.connector_token("admin", *ALL)
    arguments = {
        "search_users": {"query": "a"},
        "get_student": {"user_id": str(USER)},
        "get_group": {"group_id": str(GROUP)},
    }

    async with world.session("admin", token) as session:
        for name in sorted(ADMIN_READ_TOOLS):
            result = await call(session, name, **arguments.get(name, {}))
            assert not result.isError, (name, text_of(result))

    assert sorted(tool for tool, _, _ in world.admin_tools.calls) == sorted(
        ADMIN_READ_TOOLS
    )
