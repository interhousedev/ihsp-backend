"""Students tool `create_notebook`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.idempotency import IdempotencyKey, once
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "notebooks:write"


def register(kit: ToolKit) -> None:
    """Register `create_notebook`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec())
    async def create_notebook(
        title: Annotated[
            str,
            Field(min_length=1, max_length=200, description="Name of the notebook."),
        ],
        idempotency_key: IdempotencyKey = None,
    ) -> dict[str, Any]:
        """Create an empty personal notebook for the student."""
        actor = current_actor()

        async def create() -> dict[str, Any]:
            found = await kit.deps.content_tools.create_notebook(actor, title)
            return {
                **found,
                "links": kit.deps.web_links.notebook(UUID(str(found["id"]))),
            }

        return await once(
            kit,
            user_id=actor.user_id,
            tool="create_notebook",
            key=idempotency_key,
            arguments={"title": title},
            create=create,
        )
