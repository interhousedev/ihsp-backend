"""Tool: research the university of an admission university chat on the web.

Only a university chat has an answer; results younger than 14 days are reused,
a fresh search spends one web search of the student's soft limit.
"""

from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.search_web import SearchWebArgs
from app.modules.ai.domain.errors import ToolFailedError


class ResearchInstitution(ReadTool[SearchWebArgs]):
    """Web pages about the university this chat is about."""

    name = "research_institution"
    description = (
        "Only in a university chat: search the web about this university "
        "(admission, deadlines, programs, scholarships); cite the page url."
    )
    args_model = SearchWebArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound admission source."""
        self.bindings = bindings

    async def run(self, args: SearchWebArgs, ctx: ToolContext) -> dict[str, Any]:
        """Search (or reuse a recent search) and return the pages."""
        source = self.bindings.uni_chat
        if source is None:
            raise ToolFailedError(support_details="university research is unavailable")
        found = await source.research(ctx.actor, ctx.chat_id, args.query, ctx.locale)
        if found is None:
            raise ToolFailedError(support_details="this chat is not a university chat")
        return found
