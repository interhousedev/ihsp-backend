"""Students tool `get_test`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.content_results import test_result
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "tests:read"


def register(kit: ToolKit) -> None:
    """Register `get_test`."""

    @kit.tool(SCOPE)
    async def get_test(
        test_id: Annotated[UUID, Field(description="Test id from list_tests.")],
    ) -> dict[str, Any]:
        """Show one of the student's own tests with its questions and answers."""
        actor = current_actor()
        found = await kit.deps.content_tools.get_test(actor.user_id, test_id)
        return test_result(kit.deps, found)
