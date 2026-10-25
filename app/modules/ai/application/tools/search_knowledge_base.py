"""Tool: search the school knowledge base; an empty result is reported."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.ports.knowledge import (
    KnowledgeEntry,
    KnowledgeGapReporter,
    KnowledgeLookup,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.school_knowledge import Audience

import structlog
from pydantic import Field

log = structlog.get_logger(__name__)

HIT_LIMIT = 5
NOT_FOUND = (
    "Nothing was found in the school knowledge base. Tell the user that you do "
    "not know this and that the administration was informed; do not guess or "
    "invent facts."
)
_ROLE_ORDER = (Role.ADMIN, Role.LMS_ADMIN, Role.TEACHER, Role.LIBRARIAN, Role.STUDENT)


class SearchKnowledgeBaseArgs(ToolArgs):
    """What to look up."""

    query: str = Field(min_length=1, max_length=300)


def role_name(actor: Actor) -> str:
    """The most powerful global role of the actor (for the report only)."""
    for role in _ROLE_ORDER:
        if role in actor.roles:
            return role.value
    return "unknown"


def entry_dict(entry: KnowledgeEntry) -> dict[str, Any]:
    """One entry as the model sees it."""
    return {
        "key": entry.key,
        "title": entry.title,
        "value": entry.value,
        "tags": list(entry.tags),
    }


async def report_gap(
    reporter: KnowledgeGapReporter | None,
    query: str,
    *,
    chat_kind: str,
    chat_id: UUID | None,
    notebook_id: UUID | None,
    actor: Actor,
    audience: Audience,
) -> None:
    """Tell the administrators about the query; a failure is logged, never raised."""
    if reporter is None:
        return
    try:
        await reporter.report(
            query,
            chat_kind=chat_kind,
            chat_id=chat_id,
            notebook_id=notebook_id,
            user_role=role_name(actor),
            audience=audience,
        )
    except Exception as exc:  # the answer must not depend on the report
        log.warning("knowledge_gap_report_failed", error_type=type(exc).__name__)


class SearchKnowledgeBase(ReadTool[SearchKnowledgeBaseArgs]):
    """Facts about the school: rules, schedules, staff, procedures, contacts."""

    name = "search_knowledge_base"
    description = (
        "Search the school knowledge base (rules, schedules, staff, procedures, "
        "events, contacts, policies). Call it before answering any school-specific "
        "question you cannot answer from the context. Returns key, title, value "
        "and tags of the best entries, or says that nothing was found."
    )
    args_model = SearchKnowledgeBaseArgs

    def __init__(self, bindings: LateBindings, chat_kind: str) -> None:
        """Store the late-bound ports and the kind of chat.

        The student assistant searches as a student; the administration assistant
        as staff.
        """
        self.bindings = bindings
        self.chat_kind = chat_kind
        self.audience: Audience = "student" if chat_kind == "student" else "staff"

    async def run(
        self, args: SearchKnowledgeBaseArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the entries, or the not-found note after reporting the gap."""
        lookup: KnowledgeLookup | None = self.bindings.knowledge
        if lookup is None:
            raise ToolFailedError(support_details="knowledge base is not available")
        query = args.query.strip()
        audience = self.audience
        hits = await lookup.search(query, limit=HIT_LIMIT, audience=audience)
        if hits:
            return {"found": True, "items": [entry_dict(h) for h in hits]}
        await report_gap(
            self.bindings.knowledge_gaps,
            query,
            chat_kind=self.chat_kind,
            chat_id=ctx.chat_id,
            notebook_id=None,
            actor=ctx.actor,
            audience=audience,
        )
        return {"found": False, "items": [], "note": NOT_FOUND}
