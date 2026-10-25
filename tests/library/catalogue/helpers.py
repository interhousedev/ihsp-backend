"""Helpers of the catalogue tests: searchable items, tags, indexed pages."""

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from app.modules.library.domain.catalogue_books import BookData
from app.modules.library.domain.catalogue_search import SearchHit
from app.modules.library.domain.entities import Item, SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    ItemLanguage,
    ItemType,
    Rights,
    ShelfState,
    Visibility,
)
from app.modules.library.domain.search_query import build_search_text
from app.modules.library.infrastructure.orm import (
    Collection,
    CollectionItem,
    ShelfEntry,
    Topic,
)
from app.modules.library.ports.page_repository import IndexedPage
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from app.shared.text import search_normalize

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Store = Callable[[Item], Awaitable[Item]]


def searchable(item: Item) -> Item:
    """Fill `search_text` the way the application does."""
    item.search_text = build_search_text(
        language=item.language,
        title=item.title,
        subtitle=item.subtitle,
        authors=item.authors,
        description=item.description,
    )
    return item


async def put(
    uow_factory: UowFactory,
    store: Store,
    item: Item,
    *,
    subjects: Sequence[SubjectLink] = (),
    topics: Sequence[TopicLink] = (),
    pages: Sequence[str] = (),
) -> Item:
    """Store the item with its tags and indexed pages (one file, page numbers 1..n)."""
    searchable(item)
    await store(item)
    async with uow_factory() as uow:
        if subjects:
            await uow.items.set_subject_links(item.id, subjects)
        if topics:
            await uow.items.set_topic_links(item.id, topics)
        if pages and item.files:
            await uow.pages.replace(
                item.id, item.files[0].file_id, indexed(pages, item.language.value)
            )
        await uow.commit()
    return item


def indexed(pages: Sequence[str], language: str) -> list[IndexedPage]:
    """Pages as the scan job indexes them."""
    code = "uz" if language.startswith("uz") else language
    return [
        IndexedPage(number, text, search_normalize(text, code))
        for number, text in enumerate(pages, start=1)
    ]


def hit_ids(hits: Sequence[SearchHit]) -> list[UUID]:
    """Ids of search hits, for comparing result order."""
    return [hit.item_id for hit in hits]


async def add_shelf(
    maker: async_sessionmaker[AsyncSession], actor: Actor, item: Item, state: ShelfState
) -> None:
    """Put the item on the actor's shelf."""
    async with maker.begin() as session:
        session.add(
            ShelfEntry(
                id=new_id(), user_id=actor.user_id, item_id=item.id, state=state.value
            )
        )


async def add_collection(
    maker: async_sessionmaker[AsyncSession], items: Sequence[Item]
) -> UUID:
    """A published collection with the items; returns its id."""
    collection_id = new_id()
    async with maker.begin() as session:
        session.add(
            Collection(
                id=collection_id,
                slug=f"c-{collection_id.hex[-8:]}",
                title={"uz": "Tanlov"},
                description={},
                published=True,
            )
        )
        await session.flush()
        for position, item in enumerate(items):
            session.add(
                CollectionItem(
                    collection_id=collection_id, item_id=item.id, position=position
                )
            )
    return collection_id


async def add_topic(
    maker: async_sessionmaker[AsyncSession], subject_id: UUID, name: str = "Kinematika"
) -> UUID:
    """A topic of the subject; returns its id."""
    topic_id = new_id()
    async with maker.begin() as session:
        session.add(
            Topic(
                id=topic_id,
                subject_id=subject_id,
                name={"uz": name},
                slug=f"t-{topic_id.hex[-8:]}",
            )
        )
    return topic_id


def make_book_data(*, subjects: list[SubjectLink], **changes: object) -> BookData:
    """A complete, publishable form (official textbook, lyceum only)."""
    base = BookData(
        title="Physics 10",
        authors=["A. Author"],
        language=ItemLanguage.UZ_LATN,
        type=ItemType.TEXTBOOK,
        subjects=subjects,
        rights=Rights.OFFICIAL,
        rights_basis={"reference": "Order 12/2024"},
        visibility=Visibility.LYCEUM,
    )
    return base.model_copy(update=changes)
