"""Students tool `list_notebooks`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `list_notebooks`."""

    @kit.tool(SCOPE)
    async def list_notebooks(
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most notebooks, 1 to 50.")
        ] = 30,
    ) -> dict[str, Any]:
        """List the student's notebooks, pinned first, then most recently opened."""
        actor = current_actor()
        page = await kit.deps.history_tools.list_notebooks(
            actor, cursor=cursor, limit=limit
        )
        links = kit.deps.web_links
        return mark_untrusted(
            {
                "notebooks": [
                    {**row, "links": links.notebook(UUID(str(row["id"])))}
                    for row in page["notebooks"]
                ],
                "next_cursor": page["next_cursor"],
            },
            "notebooks[].title",
        )
