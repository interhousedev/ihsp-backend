"""Adapter: the knowledge module's search, limited to guest-accessible entries."""

from typing import Any

from app.modules.posts.ports.repositories import GuestKnowledgeHit

import structlog

log = structlog.get_logger(__name__)


class GuestKnowledgeAdapter:
    """`GuestKnowledge` over the knowledge search with ``audience="guest"``.

    The audience filter is the knowledge module's contract (entries with
    `accessible_to_guest`). When the search does not take it, nothing is returned:
    a guest never falls back to the unfiltered knowledge base.
    """

    def __init__(self, search: Any) -> None:
        """Store the knowledge module's search port."""
        self.search_port = search

    async def search(self, query: str, *, limit: int = 5) -> list[GuestKnowledgeHit]:
        """Guest-accessible hits, best first."""
        try:
            hits = await self.search_port.search(query, limit=limit, audience="guest")
        except TypeError:
            log.error("guest_knowledge.no_audience_filter")
            return []
        return [
            GuestKnowledgeHit(title=hit.title or hit.key, value=hit.value)
            for hit in hits
        ]
