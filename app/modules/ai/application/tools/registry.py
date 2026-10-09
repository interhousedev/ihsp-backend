"""The tools of each assistant."""

from collections.abc import Sequence
from typing import Any

from app.modules.ai.application.tools.base import Tool
from app.modules.ai.domain.assistant import Assistant


class ToolRegistry:
    """Looks tools up by assistant and name; the list order stays constant."""

    def __init__(
        self,
        student: Sequence[Tool],
        admin: Sequence[Tool],
        author: Sequence[Tool] = (),
    ) -> None:
        """Index the tools of the three assistants."""
        self._tools: dict[Assistant, dict[str, Tool]] = {
            Assistant.STUDENT: {tool.name: tool for tool in student},
            Assistant.ADMIN: {tool.name: tool for tool in admin},
            Assistant.LMS_AUTHOR: {tool.name: tool for tool in author},
        }

    def get(self, assistant: Assistant, name: str) -> Tool | None:
        """Return the tool or None for an unknown name."""
        return self._tools[assistant].get(name)

    def llm_tools(self, assistant: Assistant) -> list[dict[str, Any]]:
        """Return the tool list of a model request (OpenAI function format)."""
        return [tool.spec().to_llm() for tool in self._tools[assistant].values()]
