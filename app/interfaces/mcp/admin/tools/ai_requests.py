"""Administration tool `ai_list_requests`."""

from typing import Annotated, Any

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "audit:read"


def register(kit: ToolKit) -> None:
    """Register `ai_list_requests`."""

    @kit.tool(SCOPE)
    async def ai_list_requests(
        owner_app: Annotated[
            str | None,
            Field(max_length=32, description="Owner module, e.g. notebooks."),
        ] = None,
        pipeline: Annotated[
            str | None, Field(max_length=32, description="Pipeline, e.g. studio.")
        ] = None,
    ) -> dict[str, Any]:
        """List the AI requests the code registered, with their prompt version state."""
        arguments = {"owner_app": owner_app, "pipeline": pipeline}
        return await call_admin_tool(kit, "ai_list_requests", arguments)
