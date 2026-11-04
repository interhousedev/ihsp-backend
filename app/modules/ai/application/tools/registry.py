"""The tools of each assistant."""

from collections.abc import Sequence
from typing import Any, Final

from app.modules.ai.application.tools.base import Tool
from app.modules.ai.domain.assistant import Assistant

PROJECT_TOOL: Final = "search_project_files"
# Still callable (an earlier answer may have used them) but not offered to the model:
# make_document does the same job with a far smaller schema.
_NOT_OFFERED: Final[dict[Assistant, frozenset[str]]] = {
    Assistant.STUDENT: frozenset(
        {"create_presentation", "create_document", "create_spreadsheet"}
    ),
}


class ToolRegistry:
    """Looks tools up by assistant and name; the list order stays constant.

    What the model is offered can be smaller than what `get` finds. Authorization
    does not depend on the list: each tool checks the actor when it runs.
    """

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

    def llm_tools(
        self, assistant: Assistant, *, in_project: bool = True
    ) -> list[dict[str, Any]]:
        """Return the tool list of a model request (OpenAI function format).

        The list is stable within a chat, so the provider's prompt cache keeps
        working. The author assistant keeps its full schemas.
        """
        hidden = _NOT_OFFERED.get(assistant, frozenset())
        if not in_project:
            hidden |= {PROJECT_TOOL}
        compact = assistant is not Assistant.LMS_AUTHOR
        return [
            tool.spec().to_llm(compact=compact)
            for tool in self._tools[assistant].values()
            if tool.name not in hidden
        ]
