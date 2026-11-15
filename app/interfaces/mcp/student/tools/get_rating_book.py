"""Students tool `get_rating_book`."""

from typing import Any

from app.interfaces.mcp.constants import EMIS_FETCH_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "rating_book:read"


def register(kit: ToolKit) -> None:
    """Register `get_rating_book`."""

    @kit.tool(SCOPE, limit=EMIS_FETCH_LIMIT)
    async def get_rating_book() -> dict[str, Any]:
        """Get a link to the student's own rating book, a PDF that EMIS builds.

        Each call asks EMIS, so call it only when the student wants the document.
        If EMIS rejects the saved password, the student must enter it again on the
        platform.
        """
        actor = current_actor()
        return {"url": await kit.deps.academic_tools.rating_book(actor)}
