"""Students tool `list_files`."""

from typing import Annotated, Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "files:read"


def register(kit: ToolKit) -> None:
    """Register `list_files`."""

    @kit.tool(SCOPE)
    async def list_files(
        limit: Annotated[int, Field(ge=1, le=100, description="Most files.")] = 50,
    ) -> dict[str, Any]:
        """List the student's own files (My files), newest first.

        `has_text` tells whether read_file can return the file's text.
        """
        actor = current_actor()
        files = await kit.deps.files.list_owned(actor.user_id, limit=limit)
        return {
            "files": [
                {
                    "file_id": item.id,
                    "name": item.name,
                    "content_type": item.content_type,
                    "byte_size": item.byte_size,
                    "has_text": item.text_bytes is not None,
                    "text_bytes": item.text_bytes,
                }
                for item in files
            ]
        }
