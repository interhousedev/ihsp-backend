"""List knowledge entries for the administrator: by search or by recent change."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.knowledge.application.search_entries import (
    ScoredEntry,
    SearchEntries,
)
from app.modules.knowledge.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class EntryPage:
    """A page of entries; `score` is set only for a search."""

    items: list[ScoredEntry]
    total: int


class ListEntries:
    """With `q` the hybrid search; without it the newest changes first."""

    def __init__(self, *, uow_factory: UowFactory, search: SearchEntries) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._search = search

    async def execute(
        self,
        *,
        q: str | None = None,
        tags: Sequence[str] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> EntryPage:
        """Return one page and the total count (for a search, the hits found)."""
        wanted = [tag.strip().lower() for tag in tags if tag.strip()]
        if q and q.strip():
            hits = await self._search.execute(
                q, limit=limit + offset, audience="staff", tags=wanted
            )
            return EntryPage(hits[offset:], len(hits))
        async with self._uow_factory() as uow:
            entries, total = await uow.entries.list_page(wanted, limit, offset)
        return EntryPage([ScoredEntry(entry, 0.0) for entry in entries], total)
