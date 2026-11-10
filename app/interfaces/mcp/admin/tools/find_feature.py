"""Administration tool `find_feature`."""

from typing import Any

from app.interfaces.mcp.feature_search import QueryParam, find_feature_result
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "people:read"


def register(kit: ToolKit) -> None:
    """Register `find_feature`."""

    @kit.tool(SCOPE)
    async def find_feature(query: QueryParam) -> dict[str, Any]:
        """Find where a feature lives in the apps: titles and links of the pages.

        Only pages the signed-in user may open are returned. A bot command has a
        `command` and no `url`.
        """
        return find_feature_result(kit.deps, current_actor(), query)
