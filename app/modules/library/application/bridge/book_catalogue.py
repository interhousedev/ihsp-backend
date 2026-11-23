"""`LibraryBookCatalogue`: published books for other modules (admission courses)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.catalogue.common import anonymous_cards
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    ItemSort,
    ItemSource,
    viewer_from_actor,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemStatus
from app.modules.library.domain.search_query import parse_query
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.library import LibraryBookCard, LibraryBookPage

MAX_PAGE = 100


def _published_book(item: Item) -> bool:
    return item.kind is ItemKind.BOOK and item.status is ItemStatus.PUBLISHED


def _book(card: ItemCardView) -> LibraryBookCard | None:
    if card.id is None:
        return None
    return LibraryBookCard(
        id=card.id,
        slug=card.slug or str(card.id),
        title=card.title,
        author_label=card.author_label,
        cover_url=card.cover_url,
        language=card.language,
        year_published=card.year_published,
        page_count=card.page_count,
    )


class LibraryBookCatalogueImpl:
    """Search and look up published books under the actor's visibility."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        cards: CardBuilder,
        identity: IdentityDirectory,
        settings: LibrarySettings,
    ) -> None:
        """Store the unit of work factory, the card builder and the settings."""
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity
        self.settings = settings

    async def search_books(
        self, actor: Actor, query: str | None, *, limit: int, offset: int
    ) -> LibraryBookPage:
        """Published books the actor may see; an unparsable query finds nothing."""
        limit = max(1, min(limit, MAX_PAGE))
        text = parse_query(query) if query and query.strip() else None
        if query and query.strip() and text is None:
            return LibraryBookPage(items=[], has_more=False)
        filters = ItemFilters(
            query=text,
            source=ItemSource.BOOK,
            sort=ItemSort.RELEVANCE if text else ItemSort.NEWEST,
        )
        viewer = viewer_from_actor(
            actor, anonymous_cards=anonymous_cards(self.settings)
        )
        locale = await resolve_locale(self.identity, actor)
        async with self.uow_factory() as uow:
            found = await uow.items.search(
                filters, viewer, limit=limit + 1, offset=offset
            )
            page = found[:limit]
            items = await uow.items.get_many([hit.item_id for hit in page])
            ordered = [
                items[hit.item_id]
                for hit in page
                if hit.item_id in items and _published_book(items[hit.item_id])
            ]
            cards = await self.cards.build(uow, ordered, viewer=actor, locale=locale)
        books = [b for b in map(_book, cards) if b is not None]
        return LibraryBookPage(items=books, has_more=len(found) > limit)

    async def books_by_ids(
        self, actor: Actor, item_ids: Sequence[UUID]
    ) -> list[LibraryBookCard]:
        """The books that are published and visible, in the order asked."""
        if not item_ids:
            return []
        locale = await resolve_locale(self.identity, actor)
        anonymous = anonymous_cards(self.settings)
        async with self.uow_factory() as uow:
            found = await uow.items.get_many(list(item_ids))
            ordered = [
                found[i]
                for i in item_ids
                if i in found
                and _published_book(found[i])
                and can_view(found[i], actor, anonymous_cards=anonymous)
            ]
            cards = await self.cards.build(uow, ordered, viewer=actor, locale=locale)
        return [b for b in map(_book, cards) if b is not None]
