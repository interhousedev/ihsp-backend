"""Students tool `list_notebook_outputs`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `list_notebook_outputs`."""

    @kit.tool(SCOPE)
    async def list_notebook_outputs(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
    ) -> dict[str, Any]:
        """List the Studio outputs of a notebook with their status."""
        actor = current_actor()
        rows = await kit.deps.content_tools.list_notebook_outputs(actor, notebook_id)
        result = mark_untrusted({"outputs": rows}, "outputs[].title")
        result["links"] = kit.deps.web_links.notebook(notebook_id)
        return result
