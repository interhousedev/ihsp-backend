"""Students tool `list_tests`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "tests:read"


def register(kit: ToolKit) -> None:
    """Register `list_tests`."""

    @kit.tool(SCOPE)
    async def list_tests(
        limit: Annotated[
            int, Field(ge=1, le=100, description="Most tests to return, 1 to 100.")
        ] = 50,
    ) -> dict[str, Any]:
        """List the student's own tests, without their questions."""
        actor = current_actor()
        rows = await kit.deps.content_tools.list_tests(actor.user_id, limit=limit)
        links = kit.deps.web_links
        return mark_untrusted(
            {
                "tests": [
                    {
                        **row,
                        "links": links.quiz(
                            UUID(str(row["notebook_id"])), UUID(str(row["id"]))
                        ),
                    }
                    for row in rows
                ]
            },
            "tests[].title",
            "tests[].notebook_title",
        )
