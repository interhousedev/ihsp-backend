"""Tool: the student's own files."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.files import FilesApi

LIST_LIMIT = 50


class ListFilesArgs(ToolArgs):
    """No arguments."""


class ListFiles(ReadTool[ListFilesArgs]):
    """Files in My files."""

    name = "list_files"
    description = (
        "List the files in the student's My files: id, name, type and size. "
        "Use read_file with an id to read a file."
    )
    args_model = ListFilesArgs

    def __init__(self, files: FilesApi) -> None:
        """Store the files API."""
        self.files = files

    async def run(self, args: ListFilesArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the owner's files (an empty search lists the newest ones)."""
        rows = await self.files.search_text(ctx.actor.user_id, "", LIST_LIMIT)
        return capped(rows)
