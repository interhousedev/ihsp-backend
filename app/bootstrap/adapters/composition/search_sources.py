"""SearchSources over the notebooks and library modules."""

from uuid import UUID

from app.interfaces.http.v1.composition.ports import JsonObject
from app.modules.library.application.catalogue.list_items import (
    ListItems,
    ListItemsQuery,
)
from app.shared.actor import Actor
from app.shared.contracts.notebooks import NotebooksQueries

# Notebooks read for their source titles; a student has far fewer than this.
MAX_NOTEBOOKS = 50


class SearchSourcesAdapter:
    """Composition <- notebooks and library: the searches the contracts lack."""

    def __init__(self, notebooks: NotebooksQueries, list_items: ListItems) -> None:
        """Keep the notebooks queries and the catalogue search use case."""
        self._notebooks = notebooks
        self._list_items = list_items

    async def notebooks(
        self, user_id: UUID, query: str, limit: int
    ) -> list[JsonObject]:
        """Return notebooks whose title or a source title contains the query."""
        needle = query.strip().casefold()
        found: list[JsonObject] = []
        for row in await self._notebooks.list_notebooks(user_id, MAX_NOTEBOOKS):
            title = str(row.get("title") or "")
            matched: list[str] = []
            detail = await self._notebooks.get_notebook(user_id, UUID(str(row["id"])))
            for source in (detail or {}).get("sources", []):
                if needle in str(source.get("title") or "").casefold():
                    matched.append(str(source["title"]))
            if needle in title.casefold() or matched:
                found.append(
                    {
                        "id": row["id"],
                        "title": title,
                        "emoji": row.get("emoji"),
                        "source_count": row.get("source_count", 0),
                        "matched_sources": matched[:3],
                    }
                )
            if len(found) >= limit:
                break
        return found

    async def library_items(
        self, actor: Actor, query: str, limit: int
    ) -> list[JsonObject]:
        """Return the first catalogue cards the actor may see for the query."""
        page = await self._list_items.execute(
            actor, ListItemsQuery(q=query.strip(), limit=limit)
        )
        return [
            {
                "id": card.id,
                "slug": card.slug,
                "title": card.title,
                "author_label": card.author_label,
                "kind": str(card.kind),
            }
            for card in page.items
            if card.id is not None
        ][:limit]
