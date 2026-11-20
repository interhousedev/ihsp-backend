"""The read-only AI harness tools of the Administration server."""

from app.interfaces.mcp.constants import ADMIN_READ_TOOLS, SCOPES_BY_SERVER
from tests.mcp.conftest import World
from tests.mcp.helpers import call

AI_TOOLS = {
    "ai_list_requests",
    "ai_list_prompts",
    "ai_prompt_versions",
    "ai_prompt_diff",
    "ai_request_stats",
    "ai_spend",
    "ai_pipelines",
}
ALL = SCOPES_BY_SERVER["admin"]


def test_the_ai_tools_are_admin_read_tools() -> None:
    assert AI_TOOLS <= ADMIN_READ_TOOLS


async def test_ai_tools_forward_arguments_and_drop_none(world: World) -> None:
    token, actor = world.connector_token("admin", *ALL)

    async with world.session("admin", token) as session:
        await call(session, "ai_list_requests", owner_app="notebooks")
        await call(session, "ai_prompt_diff", task="chat", name="main", from_version=1)
        await call(session, "ai_request_stats", group_by="pipeline")
        await call(session, "ai_spend", by="user", limit=5)
        await call(session, "ai_pipelines")

    calls = world.admin_tools.calls
    assert [c[0] for c in calls] == [
        "ai_list_requests",
        "ai_prompt_diff",
        "ai_request_stats",
        "ai_spend",
        "ai_pipelines",
    ]
    assert calls[0][1] == {"owner_app": "notebooks"}
    assert calls[1][1] == {
        "task": "chat",
        "name": "main",
        "from_version": 1,
        "locale": "",
    }
    assert calls[2][1] == {"group_by": "pipeline"}
    assert calls[3][1] == {"by": "user", "limit": 5}
    assert calls[4][1] == {}
    assert all(c[2] == actor for c in calls)
