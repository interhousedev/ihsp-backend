"""Students tool `search_files`."""

from typing import Annotated, Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "files:read"


def register(kit: ToolKit) -> None:
    """Register `search_files`."""

    @kit.tool(SCOPE)
    async def search_files(
        query: Annotated[
            str, Field(min_length=1, max_length=200, description="Words to look for.")
        ],
        limit: Annotated[int, Field(ge=1, le=20, description="Most results.")] = 10,
    ) -> dict[str, Any]:
        """Search the text of the student's own files; returns ids with snippets."""
        actor = current_actor()
        results = await kit.deps.files.search_text(actor.user_id, query, limit)
        return {"results": results}
