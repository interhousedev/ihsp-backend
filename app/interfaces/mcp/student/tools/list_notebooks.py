"""Students tool `list_notebooks`."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

SCOPE = "notebooks:read"


def register(kit: ToolKit) -> None:
    """Register `list_notebooks`."""

    @kit.tool(SCOPE)
    async def list_notebooks() -> dict[str, Any]:
        """List the student's notebooks, most recently opened first."""
        actor = current_actor()
        rows = await kit.deps.content_tools.list_notebooks(actor)
        links = kit.deps.web_links
        return mark_untrusted(
            {
                "notebooks": [
                    {**row, "links": links.notebook(UUID(str(row["id"])))}
                    for row in rows
                ]
            },
            "notebooks[].title",
        )
