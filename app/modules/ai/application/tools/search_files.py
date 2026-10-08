"""Tool: search the student's files by text."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.files import FilesApi

from pydantic import Field

SEARCH_LIMIT = 10


class SearchFilesArgs(ToolArgs):
    """A search phrase."""

    query: str = Field(min_length=1, max_length=200)


class SearchFiles(ReadTool[SearchFilesArgs]):
    """Search in the text of the student's files."""

    name = "search_files"
    description = (
        "Search the text of the student's own files; returns matching files "
        "with snippets. Then use read_file to read a file."
    )
    args_model = SearchFilesArgs

    def __init__(self, files: FilesApi) -> None:
        """Store the files API."""
        self.files = files

    async def run(self, args: SearchFilesArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the matches."""
        rows = await self.files.search_text(ctx.actor.user_id, args.query, SEARCH_LIMIT)
        return capped(rows)
