"""Tool `list_notifications`, on the Students and the Teachers servers."""

from typing import Annotated, Any, Literal

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notifications:read"


def register(kit: ToolKit) -> None:
    """Register `list_notifications`."""

    @kit.tool(SCOPE, log=LogSpec(keep=("filter", "limit")))
    async def list_notifications(
        filter: Annotated[
            Literal["all", "activity", "announcements"],
            Field(
                description="all, activity (everything but announcements) or "
                "announcements."
            ),
        ] = "all",
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most notifications, 1 to 50.")
        ] = 20,
    ) -> dict[str, Any]:
        """List the user's own platform notifications, newest first.

        Each item says whether it was read; `unread_count` counts all unread ones.
        Reading the list does not mark anything as read.
        """
        actor = current_actor()
        page = await kit.deps.history_tools.list_notifications(
            actor, filter=filter, cursor=cursor, limit=limit
        )
        return mark_untrusted(
            page,
            "notifications[].title",
            "notifications[].body",
            "notifications[].link",
        )
