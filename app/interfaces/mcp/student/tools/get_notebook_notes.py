"""Students tool `get_notebook_notes`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `get_notebook_notes`."""

    @kit.tool(SCOPE)
    async def get_notebook_notes(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
        offset: Annotated[
            int, Field(ge=0, description="Notes already read (`next_offset`).")
        ] = 0,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most notes, 1 to 50.")
        ] = 20,
    ) -> dict[str, Any]:
        """Read the notes the student wrote in one of their notebooks, one page."""
        actor = current_actor()
        page = await kit.deps.history_tools.get_notebook_notes(
            actor.user_id, notebook_id, offset=offset, limit=limit
        )
        return mark_untrusted(page, "title", "notes[].title", "notes[].text")
