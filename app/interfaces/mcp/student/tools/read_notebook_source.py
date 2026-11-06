"""Students tool `read_notebook_source`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `read_notebook_source`."""

    @kit.tool(SCOPE)
    async def read_notebook_source(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
        source_id: Annotated[UUID, Field(description="Source id from get_notebook.")],
        page: Annotated[int, Field(ge=1, le=100_000)] = 1,
    ) -> dict[str, Any]:
        """Read one 8 KB page of a source's text."""
        actor = current_actor()
        found = await kit.deps.content_tools.read_notebook_source(
            actor, notebook_id, source_id, page=page
        )
        result = mark_untrusted(found, "title", "text")
        result["links"] = kit.deps.web_links.notebook(notebook_id)
        return result
