"""Students tool `get_library_item`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "library:read"


def register(kit: ToolKit) -> None:
    """Register `get_library_item`."""

    @kit.tool(SCOPE)
    async def get_library_item(
        item_id: Annotated[UUID, Field(description="Id from search_library.")],
    ) -> dict[str, Any]:
        """Show a library item and its files."""
        actor = current_actor()
        found = await kit.deps.content_tools.get_library_item(actor, item_id)
        result = mark_untrusted(found, "title", "author_label")
        result["links"] = kit.deps.web_links.library_item(item_id)
        return result
