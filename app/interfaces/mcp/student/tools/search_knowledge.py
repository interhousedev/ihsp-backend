"""Students tool `search_knowledge`."""

from typing import Annotated, Any, Final

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import SEARCH_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "knowledge:read"
# From the server, never from the client: this server is for students.
AUDIENCE: Final = "student"


def register(kit: ToolKit) -> None:
    """Register `search_knowledge`."""

    @kit.tool(SCOPE, limit=SEARCH_LIMIT, log=LogSpec(keep=("limit",)))
    async def search_knowledge(
        query: Annotated[str, Field(min_length=2, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Search the school knowledge base: rules, procedures, staff and contacts."""
        current_actor()
        hits = await kit.deps.content_tools.search_knowledge(
            query, audience=AUDIENCE, limit=limit
        )
        return mark_untrusted(
            {"hits": hits}, "hits[].title", "hits[].value", "hits[].tags[]"
        )
