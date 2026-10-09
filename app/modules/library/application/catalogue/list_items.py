"""List and search catalogue items (GET /library/items)."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.library.application.cards import CardBuilder, Hit
from app.modules.library.application.catalogue.common import (
    anonymous_cards,
    clamp_limit,
)
from app.modules.library.application.catalogue.pages import next_cursor, read_offset
from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    ItemSort,
    ItemSource,
    viewer_from_actor,
)
from app.modules.library.domain.enums import ItemType, ShelfState, UploaderRole
from app.modules.library.domain.search_query import parse_query
from app.modules.library.ports.stats_recorder import StatsRecorder
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


@dataclass(frozen=True, slots=True)
class ListItemsQuery:
    """The query string of `GET /library/items`."""

    q: str | None = None
    source: ItemSource = ItemSource.ALL
    subject_id: UUID | None = None
    topic_id: UUID | None = None
    year_of_study: int | None = None
    type: ItemType | None = None
    language: str | None = None
    collection_id: UUID | None = None
    uploader_role: UploaderRole | None = None
    has_text: bool | None = None
    shelf: ShelfState | Literal["any"] | None = None
    sort: ItemSort = ItemSort.RELEVANCE
    cursor: str | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class CardPage:
    """A page of cards with the cursor of the next one."""

    items: list[ItemCardView]
    next_cursor: str | None


class ListItems:
    """Search and browse: filters, ranking and cursor pages, visibility included."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        cards: CardBuilder,
        identity: IdentityDirectory,
        settings: LibrarySettings,
        stats: StatsRecorder | None = None,
    ) -> None:
        """Store the unit of work factory, the card builder and the settings."""
        self.stats = stats
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity
        self.settings = settings

    async def execute(
        self,
        actor: Actor | None,
        query: ListItemsQuery,
        *,
        accept_language: str | None = None,
    ) -> CardPage:
        """The page of cards the caller may see for this query."""
        text = parse_query(query.q) if query.q else None
        if query.q and text is None:
            return CardPage(items=[], next_cursor=None)
        filters = ItemFilters(
            query=text,
            source=query.source,
            subject_id=query.subject_id,
            topic_id=query.topic_id,
            year_of_study=query.year_of_study,
            type=query.type,
            language=query.language,
            collection_id=query.collection_id,
            uploader_role=query.uploader_role,
            has_text=query.has_text,
            shelf=query.shelf,
            sort=query.sort,
        )
        viewer = viewer_from_actor(
            actor, anonymous_cards=anonymous_cards(self.settings)
        )
        limit = clamp_limit(query.limit)
        offset = read_offset(query.cursor)
        locale = await resolve_locale(self.identity, actor, accept_language)
        async with self.uow_factory() as uow:
            found = await uow.items.search(
                filters, viewer, limit=limit + 1, offset=offset
            )
            page = found[:limit]
            items = await uow.items.get_many([hit.item_id for hit in page])
            ordered = [items[hit.item_id] for hit in page if hit.item_id in items]
            hits = {
                hit.item_id: Hit(snippet=hit.snippet, page=hit.page)
                for hit in page
                if hit.snippet
            }
            cards = await self.cards.build(
                uow, ordered, viewer=actor, locale=locale, hits=hits
            )
        if query.q and offset == 0 and not cards and self.stats is not None:
            await self.stats.no_result(query.q)
        return CardPage(
            items=cards, next_cursor=next_cursor(offset, len(page), len(found) > limit)
        )
