"""Students tool `search_library`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import SEARCH_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "library:read"


def register(kit: ToolKit) -> None:
    """Register `search_library`."""

    @kit.tool(SCOPE, limit=SEARCH_LIMIT, log=LogSpec(keep=("limit",)))
    async def search_library(
        query: Annotated[
            str,
            Field(min_length=2, max_length=500, description="Words to search for."),
        ],
        limit: Annotated[
            int, Field(ge=1, le=20, description="Most items to return, 1 to 20.")
        ] = 10,
    ) -> dict[str, Any]:
        """Search the school library's books and materials the student may see."""
        actor = current_actor()
        rows = await kit.deps.content_tools.search_library(actor, query, limit=limit)
        links = kit.deps.web_links
        return mark_untrusted(
            {
                "items": [
                    {**row, "links": links.library_item(UUID(str(row["id"])))}
                    for row in rows
                ]
            },
            "items[].title",
            "items[].author_label",
            "items[].snippet",
        )
