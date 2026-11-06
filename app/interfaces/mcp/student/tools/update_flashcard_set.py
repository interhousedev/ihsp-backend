"""Students tool `update_flashcard_set`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.content_results import flashcard_set_result
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:write"


def register(kit: ToolKit) -> None:
    """Register `update_flashcard_set`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        log=LogSpec(keep=("set_id", "shuffle", "new_per_day", "reviews_per_day")),
    )
    async def update_flashcard_set(
        set_id: Annotated[UUID, Field(description="Set id from list_flashcard_sets.")],
        shuffle: Annotated[
            bool | None,
            Field(description="Mix the order of reviews and new cards each day."),
        ] = None,
        new_per_day: Annotated[
            int | None, Field(ge=1, le=200, description="New cards a day, 1 to 200.")
        ] = None,
        reviews_per_day: Annotated[
            int | None, Field(ge=1, le=2000, description="Reviews a day, 1 to 2000.")
        ] = None,
    ) -> dict[str, Any]:
        """Change the study settings of one of the student's sets; the rest stays."""
        actor = current_actor()
        if shuffle is None and new_per_day is None and reviews_per_day is None:
            raise McpInvalidInputError(params={"reason": "give a setting to change"})
        found = await kit.deps.flashcards.update_set_settings(
            actor.user_id,
            set_id,
            shuffle=shuffle,
            new_per_day=new_per_day,
            reviews_per_day=reviews_per_day,
        )
        return flashcard_set_result(kit.deps, found)
