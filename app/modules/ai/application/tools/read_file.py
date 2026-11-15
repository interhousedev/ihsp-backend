"""Tool: read one page of a file's text."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.files import FilesApi
from app.shared.limits import LimitsProvider

from pydantic import Field

LARGE_FILE_PAGES = 12  # about 100 KB of text


class ReadFileArgs(ToolArgs):
    """A file and a page number."""

    file_id: UUID
    page: int = Field(default=1, ge=1, le=1000)


class ReadFile(ReadTool[ReadFileArgs]):
    """One 8 KB page of a file's extracted text (FILE-7)."""

    name = "read_file"
    description = "Use to read a page of an own file or a lesson attachment."
    args_model = ReadFileArgs

    def __init__(self, files: FilesApi, limits: LimitsProvider) -> None:
        """Store the files API and the limits (the largest text the assistant reads)."""
        self.files = files
        self.limits = limits

    async def run(self, args: ReadFileArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the page, or fail with a message the model can relay."""
        ref = await self.files.get(args.file_id)
        if ref is None or not await self.files.check_access(args.file_id, ctx.actor):
            raise ToolFailedError(support_details="file not found")
        if ref.status != "ready":
            raise ToolFailedError(support_details="the file is not ready yet")
        if ref.text_bytes is None:
            raise ToolFailedError(support_details="no text could be read from the file")
        max_text_bytes = (await self.limits.current()).ai_text_max_bytes
        if ref.text_bytes > max_text_bytes:
            raise ToolFailedError(
                support_details=(
                    f"the text of this file is {ref.text_bytes} bytes, over the "
                    f"limit of {max_text_bytes} bytes; tell the user to split the "
                    f"file or upload only the needed chapters"
                )
            )
        page = await self.files.read_text_page(args.file_id, args.page)
        result: dict[str, Any] = {
            "file_id": str(ref.id),
            "name": ref.name,
            "page": page.page,
            "pages": page.pages,
            "text": page.text,
        }
        if page.pages > LARGE_FILE_PAGES:
            result["note"] = (
                f"Large file of {page.pages} pages: do not read it all. Use "
                "search_files for the relevant part and open only those pages, "
                "or make a notebook from the file."
            )
        return result
