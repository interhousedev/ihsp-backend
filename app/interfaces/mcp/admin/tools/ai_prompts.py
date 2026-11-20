"""Administration tools `ai_list_prompts`, `ai_prompt_versions`, `ai_prompt_diff`."""

from typing import Annotated, Any, Literal

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "audit:read"
Task = Annotated[str, Field(max_length=64, description="AI task, e.g. studio_quiz.")]
Name = Annotated[str, Field(max_length=64, description="Prompt slot name.")]
Locale = Annotated[
    Literal["", "uz", "ru", "en"],
    Field(description="Text locale; empty is the text for every locale."),
]


def register(kit: ToolKit) -> None:
    """Register the prompt tools."""

    @kit.tool(SCOPE)
    async def ai_list_prompts(
        task: Annotated[
            str | None, Field(max_length=64, description="Only this AI task.")
        ] = None,
    ) -> dict[str, Any]:
        """List prompt slots with the active version, source and size of each."""
        return await call_admin_tool(kit, "ai_list_prompts", {"task": task})

    @kit.tool(SCOPE)
    async def ai_prompt_versions(
        task: Task, name: Name, locale: Locale = ""
    ) -> dict[str, Any]:
        """List the stored versions of a prompt slot (sizes and notes, no text)."""
        arguments = {"task": task, "name": name, "locale": locale}
        return await call_admin_tool(kit, "ai_prompt_versions", arguments)

    @kit.tool(SCOPE)
    async def ai_prompt_diff(
        task: Task,
        name: Name,
        from_version: Annotated[
            int | None, Field(ge=0, description="Older version; 0 is the built-in.")
        ] = None,
        to_version: Annotated[
            int | None, Field(ge=0, description="Newer version; the latest if omitted.")
        ] = None,
        locale: Locale = "",
    ) -> dict[str, Any]:
        """Show the unified diff between two versions (cut at 20 000 characters)."""
        arguments = {
            "task": task,
            "name": name,
            "from_version": from_version,
            "to_version": to_version,
            "locale": locale,
        }
        return await call_admin_tool(kit, "ai_prompt_diff", arguments)
