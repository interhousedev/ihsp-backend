"""Students tool `search_notebooks`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import SEARCH_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `search_notebooks`."""

    @kit.tool(SCOPE, limit=SEARCH_LIMIT, log=LogSpec(keep=("notebook_id", "limit")))
    async def search_notebooks(
        query: Annotated[str, Field(min_length=2, max_length=500)],
        notebook_id: Annotated[
            UUID | None,
            Field(description="Left out: the 5 most recently opened notebooks."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> dict[str, Any]:
        """Find passages in the sources of the student's notebooks."""
        actor = current_actor()
        rows = await kit.deps.content_tools.search_notebooks(
            actor, query, notebook_id=notebook_id, limit=limit
        )
        links = kit.deps.web_links
        return mark_untrusted(
            {
                "passages": [
                    {**row, "links": links.notebook(UUID(str(row["notebook_id"])))}
                    for row in rows
                ]
            },
            "passages[].source_title",
            "passages[].text",
        )
