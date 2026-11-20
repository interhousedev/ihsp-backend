"""The tools of each assistant."""

from collections.abc import Sequence
from typing import Any, Final

from app.modules.ai.application.tools.app_skills import AppSkill, skill_for
from app.modules.ai.application.tools.base import Tool
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.prompts import SURFACE_TELEGRAM

PROJECT_TOOL: Final = "search_project_files"
UNI_TOOL: Final = "research_institution"
# Offered only by an app skill that names them (see app_skills.py).
_APP_ONLY: Final = frozenset({"library_search"})
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
        telegram: Sequence[Tool] = (),
        admission: Sequence[Tool] = (),
        staff: Sequence[Tool] = (),
    ) -> None:
        """Index the tools of the assistants.

        `telegram` tools are offered to every assistant, on the bot's surface only.
        `staff` is the teachers' pool, offered by the staff app's skill on the student
        assistant.
        """
        self._telegram = {tool.name: tool for tool in telegram}
        self._staff = {tool.name: tool for tool in staff}
        self._tools: dict[Assistant, dict[str, Tool]] = {
            Assistant.STUDENT: {tool.name: tool for tool in student},
            Assistant.ADMIN: {tool.name: tool for tool in admin},
            Assistant.LMS_AUTHOR: {tool.name: tool for tool in author},
            Assistant.ADMISSION: {tool.name: tool for tool in admission},
        }

    def get(self, assistant: Assistant, name: str) -> Tool | None:
        """Return the tool or None for an unknown name.

        The teachers' pool is found on the student assistant, where its skill offers it.
        """
        found = self._tools[assistant].get(name) or self._telegram.get(name)
        if found is None and assistant is Assistant.STUDENT:
            found = self._staff.get(name)
        return found

    def llm_tools(
        self,
        assistant: Assistant,
        *,
        in_project: bool = True,
        in_uni_chat: bool = False,
        surface: str = "web",
        app: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the tool list of a model request (OpenAI function format).

        The list is stable within a chat, so the provider's prompt cache keeps
        working. An app skill narrows the list: the staff skill offers the teachers'
        pool, other skills their named tools of this assistant's pool; otherwise the
        default list is offered. The author assistant keeps its full schemas. The
        university research tool is offered only in an admission university chat.
        """
        skill = skill_for(app)
        pool = self._pool(assistant, skill)
        hidden = self._hidden(assistant, pool, skill)
        if not in_project:
            hidden |= {PROJECT_TOOL}
        if not in_uni_chat:
            hidden |= {UNI_TOOL}
        compact = assistant is not Assistant.LMS_AUTHOR
        tools = [t for t in pool.values() if t.name not in hidden]
        if surface == SURFACE_TELEGRAM:
            tools += list(self._telegram.values())
        return [tool.spec().to_llm(compact=compact) for tool in tools]

    def _pool(self, assistant: Assistant, skill: AppSkill | None) -> dict[str, Tool]:
        """The tools a skill can offer: the teachers' pool or the assistant's own."""
        if skill is not None and skill.staff_pool and skill.assistant is assistant:
            return self._staff
        return self._tools[assistant]

    def _hidden(
        self, assistant: Assistant, pool: dict[str, Tool], skill: AppSkill | None
    ) -> frozenset[str]:
        """Tool names of the pool that the model is not offered for this skill."""
        if skill is None or skill.assistant is not assistant or skill.tools is None:
            return _NOT_OFFERED.get(assistant, frozenset()) | _APP_ONLY
        return frozenset(pool) - skill.tools
