"""Adapters: the knowledge module and the notify module as AI collaborators.

The assistants and the notebook chat know only the contracts in
`app.shared.contracts.school_knowledge`; these classes connect them to the public
APIs of the knowledge and notify modules.
"""

from uuid import UUID

from app.modules.knowledge.application.public_api import KnowledgeSearchPort
from app.shared.contracts.notify import KnowledgeGapNotifier
from app.shared.contracts.school_knowledge import KnowledgeEntry


class KnowledgeLookupAdapter:
    """`KnowledgeLookup` over the knowledge module's search."""

    def __init__(self, search: KnowledgeSearchPort) -> None:
        """Store the module's search port."""
        self.search_port = search

    async def search(self, query: str, *, limit: int = 5) -> list[KnowledgeEntry]:
        """Search and map the hits (a missing title falls back to the key)."""
        hits = await self.search_port.search(query, limit=limit)
        return [
            KnowledgeEntry(
                key=hit.key,
                title=hit.title or hit.key,
                value=hit.value,
                tags=tuple(hit.tags),
                score=hit.score,
            )
            for hit in hits
        ]


class KnowledgeGapAdapter:
    """`KnowledgeGapReporter` over the notify module's administrator alert."""

    def __init__(self, notifier: KnowledgeGapNotifier) -> None:
        """Store the notify module's public API."""
        self.notifier = notifier

    async def report(
        self,
        query: str,
        *,
        chat_kind: str,
        chat_id: UUID | None,
        notebook_id: UUID | None,
        user_role: str,
    ) -> None:
        """Notify the administrators (notify deduplicates for 24 hours)."""
        await self.notifier.notify_knowledge_gap(
            query=query,
            chat_kind=chat_kind,
            user_role=user_role,
            chat_id=str(chat_id) if chat_id is not None else None,
            notebook_id=str(notebook_id) if notebook_id is not None else None,
        )
