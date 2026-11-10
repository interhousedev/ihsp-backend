"""The model-backed teacher tools: present only when `deps.teacher_ai` is set."""

from app.interfaces.mcp.teacher.tools import (
    ai_materials,
    ai_plans_read,
    ai_plans_write,
)
from app.interfaces.mcp.toolkit import ToolKit

AI_MODULES = (ai_materials, ai_plans_read, ai_plans_write)


def register(kit: ToolKit) -> None:
    """Register the AI tools; each module skips itself without the backend."""
    for module in AI_MODULES:
        module.register(kit)
