"""Students tool `add_notebook_sources`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import BaseModel, Field


class TextSource(BaseModel):
    """Text to add as a source."""

    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=100_000)


SCOPE = "notebooks:write"


def register(kit: ToolKit) -> None:
    """Register `add_notebook_sources`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("notebook_id",)))
    async def add_notebook_sources(
        notebook_id: Annotated[UUID, Field(description="Id from list_notebooks.")],
        file_ids: Annotated[
            list[UUID] | None,
            Field(max_length=20, description="Ids from list_files (own files)."),
        ] = None,
        texts: Annotated[list[TextSource] | None, Field(max_length=20)] = None,
    ) -> dict[str, Any]:
        """Add the student's files or text as sources of their notebook; no web pages.

        A source is read in the background: its `status` says when it is ready.
        """
        actor = current_actor()
        if not file_ids and not texts:
            raise McpInvalidInputError(params={"reason": "give file_ids or texts"})
        found = await kit.deps.content_tools.add_notebook_sources(
            actor,
            notebook_id,
            file_ids=file_ids or [],
            texts=[item.model_dump() for item in texts or []],
        )
        return {**found, "links": kit.deps.web_links.notebook(notebook_id)}
