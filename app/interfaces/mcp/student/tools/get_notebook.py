"""Students tool `get_notebook`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `get_notebook`."""

    @kit.tool(SCOPE)
    async def get_notebook(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
    ) -> dict[str, Any]:
        """Show a notebook: its summary, sources and Studio outputs."""
        actor = current_actor()
        found = await kit.deps.content_tools.get_notebook(actor, notebook_id)
        result = mark_untrusted(
            found, "title", "summary", "sources[].title", "outputs[].title"
        )
        result["links"] = kit.deps.web_links.notebook(notebook_id)
        return result
