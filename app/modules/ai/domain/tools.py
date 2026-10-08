"""Tool descriptions the model sees."""

from dataclasses import dataclass
from typing import Any

from app.modules.ai.domain.tool_call import ToolAccess

MAX_RESULT_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Name, access and JSON schema of one tool."""

    name: str
    access: ToolAccess
    description: str
    parameters: dict[str, Any]

    def to_llm(self) -> dict[str, Any]:
        """Return the OpenAI function-format entry for the model request."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def note_key(tool: str) -> str:
    """Return the i18n key of the "Looked up…" note of a tool."""
    return "ai-note-" + tool.replace("_", "-")
