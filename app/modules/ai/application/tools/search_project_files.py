"""Tool: search the files of the chat's project (only those; empty outside projects)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.contracts.files import FilesApi

from pydantic import Field

SEARCH_LIMIT = 10
# The text search covers all the student's files; the project's are picked from it.
CANDIDATES = 100


class SearchProjectFilesArgs(ToolArgs):
    """A search phrase."""

    query: str = Field(min_length=1, max_length=200)


class SearchProjectFiles(ReadTool[SearchProjectFilesArgs]):
    """Search in the text of the files attached to this chat's project."""

    name = "search_project_files"
    description = "Use to find something in the files of this chat's project."
    args_model = SearchProjectFilesArgs

    def __init__(
        self, uow_factory: Callable[[], AiUnitOfWork], files: FilesApi
    ) -> None:
        """Store the unit of work factory and the files API."""
        self.uow_factory = uow_factory
        self.files = files

    async def run(
        self, args: SearchProjectFilesArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the matches among the project's files only."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(ctx.chat_id)
            if chat is None or chat.project_id is None:
                return {"items": [], "truncated": False, "note": "not_in_project"}
            allowed = set(await uow.projects.file_ids(chat.project_id))
        if not allowed:
            return {"items": [], "truncated": False, "note": "no_files"}
        rows = await self.files.search_text(ctx.actor.user_id, args.query, CANDIDATES)
        matches = [row for row in rows if _as_uuid(row.get("file_id")) in allowed]
        return capped(matches[:SEARCH_LIMIT])


def _as_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None
