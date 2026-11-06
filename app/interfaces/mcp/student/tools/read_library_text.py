"""Students tool `read_library_text`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "library:read"


def register(kit: ToolKit) -> None:
    """Register `read_library_text`."""

    @kit.tool(SCOPE)
    async def read_library_text(
        item_id: Annotated[UUID, Field(description="Id from search_library.")],
        page: Annotated[
            int,
            Field(ge=1, le=100_000, description="Page of the text, from 1; 8 KB each."),
        ] = 1,
    ) -> dict[str, Any]:
        """Read one 8 KB page of a library item's text."""
        actor = current_actor()
        found = await kit.deps.content_tools.read_library_text(
            actor, item_id, page=page
        )
        result = mark_untrusted(found, "title", "text")
        result["links"] = kit.deps.web_links.library_item(item_id)
        return result
