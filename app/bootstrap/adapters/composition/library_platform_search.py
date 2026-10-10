"""PlatformSearch over the library catalogue (items the actor may read)."""

from app.modules.library.application.catalogue.list_items import (
    ListItems,
    ListItemsQuery,
)
from app.shared.actor import Actor
from app.shared.contracts.web_search import PlatformPassage


class LibraryPlatformSearch:
    """Library items found by full text; the passage is the hit snippet."""

    def __init__(self, list_items: ListItems) -> None:
        """Keep the catalogue search use case."""
        self._list_items = list_items

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """One passage per readable item that has text matching the query."""
        page = await self._list_items.execute(
            actor, ListItemsQuery(q=query.strip(), has_text=True, limit=limit)
        )
        found: list[PlatformPassage] = []
        for card in page.items:
            text = card.snippet or card.description_excerpt
            if card.id is None or not text:
                continue
            found.append(
                PlatformPassage(
                    title=card.title,
                    url=f"/library/{card.slug or card.id}",
                    text=text,
                    ref_kind="library_item",
                    ref_id=str(card.id),
                )
            )
        return found
