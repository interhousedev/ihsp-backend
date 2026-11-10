"""Teacher AI tool `list_plan_templates`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "lesson-plans:read"


def register(kit: ToolKit) -> None:
    """Register the tool when the process has the AI backend."""
    ai = kit.deps.teacher_ai
    if ai is None:
        return

    @kit.tool(SCOPE)
    async def list_plan_templates() -> dict[str, Any]:
        """The teacher's lesson plan templates."""
        return {"templates": to_jsonable(await ai.list_plan_templates(current_actor()))}
