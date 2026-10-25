"""Contracts: the school knowledge base and the report of unanswered questions.

Shared by the AI assistants and the notebook chat; adapters over the knowledge and
notify modules are built in the composition root.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

Audience = Literal["guest", "student", "staff"]
"""Who asks: a guest sees guest-accessible entries, a student student-accessible
ones, staff all of them."""


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """One knowledge base answer as the assistant sees it."""

    key: str
    title: str
    value: str
    tags: tuple[str, ...] = ()
    score: float = 0.0


class KnowledgeLookup(Protocol):
    """Search of the school knowledge base (rules, staff, procedures, contacts)."""

    async def search(
        self, query: str, *, limit: int = 5, audience: Audience
    ) -> list[KnowledgeEntry]:
        """Return the best entries visible to the audience for the query, best first."""
        ...


class KnowledgeGapReporter(Protocol):
    """Tells the administrators that a question found nothing in the base."""

    async def report(
        self,
        query: str,
        *,
        chat_kind: str,
        chat_id: UUID | None,
        notebook_id: UUID | None,
        user_role: str,
        audience: Audience,
    ) -> None:
        """Report the query only (never message bodies); repeats are deduplicated."""
        ...
