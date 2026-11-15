"""Search inside one item's stored page text (GET .../items/{id}/text/search)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.catalogue.common import (
    anonymous_cards,
    load_visible,
)
from app.modules.library.application.catalogue.get_item_text import readable_file
from app.modules.library.domain.page_search import (
    MIN_QUERY_CHARS,
    Snippet,
    fold_query,
    locate,
    snippet,
)
from app.modules.library.domain.search_query import item_search_language
from app.modules.library.ports.page_repository import IndexedPage
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError

MAX_HITS = 200


@dataclass(frozen=True, slots=True)
class BoxView:
    """A rectangle on a page, as fractions of it (origin top left)."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class TextHitView:
    """One occurrence: its page, the text around it and where it is."""

    page: int
    snippet: Snippet
    start: int
    end: int
    boxes: list[BoxView]
    source: str


@dataclass(frozen=True, slots=True)
class TextSearchView:
    """Hits in page order; `truncated` when more exist than were returned."""

    query: str
    hits: list[TextHitView]
    truncated: bool


class SearchItemText:
    """Case-, diacritic- and (Uzbek) script-insensitive search of the primary file."""

    def __init__(self, *, uow_factory: UowFactory, settings: LibrarySettings) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.settings = settings

    async def execute(
        self, actor: Actor | None, item_id: UUID, query: str, *, limit: int = 100
    ) -> TextSearchView:
        """Find `query` on the pages of the item (at most `limit` hits)."""
        query = " ".join(query.split())
        limit = min(max(limit, 1), MAX_HITS)
        if len(query) < MIN_QUERY_CHARS:
            raise ValidationFailedError(params={"field": "q"})
        cards = anonymous_cards(self.settings)
        async with self.uow_factory() as uow:
            item = await load_visible(uow, str(item_id), actor, cards=cards)
            stored = readable_file(item, actor, cards)
            language = item_search_language(item.language)
            needle = fold_query(query, language)
            pages = await uow.pages.search(item.id, stored.file_id, needle, limit + 1)
        hits: list[TextHitView] = []
        for page in pages:
            for found in locate(page.text, query, language, limit=limit + 1):
                hits.append(_hit(page, found.start, found.end))
        return TextSearchView(query, hits[:limit], len(hits) > limit)


def _hit(page: IndexedPage, start: int, end: int) -> TextHitView:
    boxes = [
        BoxView(b.x, b.y, b.w, b.h)
        for b in page.boxes
        if b.start < end and b.end > start
    ]
    return TextHitView(
        page.page, snippet(page.text, start, end), start, end, boxes, page.source
    )
