"""LIB-4: topics and collections survive a round trip through PostgreSQL."""

from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item, TopicLink
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.library.taxonomy.helpers import make_collection, make_topic

import pytest
from sqlalchemy.exc import IntegrityError

StoreItem = Callable[[Item], Awaitable[Item]]
SUBJECT = new_id()


async def test_topics_come_back_by_position_for_one_subject_or_all(
    uow_factory: UowFactory,
) -> None:
    """LIB-4: the tree is read per subject, ordered by position."""
    second = make_topic(SUBJECT, "Optics", position=2)
    first = make_topic(SUBJECT, "Mechanics", position=1)
    child = make_topic(SUBJECT, "Kinematics", parent_id=first.id)
    other = make_topic(new_id(), "Algebra")

    async with uow_factory() as uow:
        for topic in (second, first, child, other):
            await uow.taxonomy.add_topic(topic)
        in_subject = await uow.taxonomy.topics(SUBJECT)
        everywhere = await uow.taxonomy.topics()

    assert [t.slug for t in in_subject] == ["kinematics", "mechanics", "optics"]
    assert {t.id for t in everywhere} == {t.id for t in (second, first, child, other)}
    assert in_subject[0].parent_id == first.id


async def test_topic_update_and_lookup(uow_factory: UowFactory) -> None:
    """LIB-4: a renamed topic keeps its place."""
    topic = make_topic(SUBJECT, "Optics")
    async with uow_factory() as uow:
        await uow.taxonomy.add_topic(topic)
        topic.name = {"uz": "Optika", "ru": "Оптика", "en": "Optics"}
        topic.year_of_study = 2
        await uow.taxonomy.save_topic(topic)
        loaded = await uow.taxonomy.get_topic(topic.id)
        missing = await uow.taxonomy.get_topic(new_id())
        names = await uow.taxonomy.topic_names([topic.id])

    assert loaded is not None and loaded.name["ru"] == "Оптика"
    assert loaded.year_of_study == 2
    assert missing is None
    assert names[topic.id]["uz"] == "Optika"


async def test_siblings_cannot_share_a_slug_but_other_parents_can(
    uow_factory: UowFactory,
) -> None:
    """LIB-4: unique (subject, parent, slug), also among roots (NULL parent)."""
    root = make_topic(SUBJECT, "Root", slug="root")
    async with uow_factory() as uow:
        await uow.taxonomy.add_topic(root)
        await uow.taxonomy.add_topic(make_topic(SUBJECT, "A", parent_id=root.id, slug="x"))
        await uow.taxonomy.add_topic(make_topic(SUBJECT, "B", slug="x"))
        with pytest.raises(IntegrityError):
            await uow.taxonomy.add_topic(make_topic(SUBJECT, "C", slug="x"))


async def test_deleting_a_topic_removes_children_and_item_links(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-4: the cascade takes the subtree and the links of items."""
    book = await store_item(make_book())
    root = make_topic(SUBJECT, "Root")
    child = make_topic(SUBJECT, "Child", parent_id=root.id)
    keep = make_topic(SUBJECT, "Keep")
    async with uow_factory() as uow:
        for topic in (root, child, keep):
            await uow.taxonomy.add_topic(topic)
        await uow.items.set_topic_links(
            book.id, [TopicLink(root.id), TopicLink(child.id, 5, 9), TopicLink(keep.id)]
        )
        counted = await uow.taxonomy.count_item_links([root.id, child.id])
        await uow.taxonomy.delete_topic(root.id)
        left = await uow.taxonomy.topics(SUBJECT)
        links = await uow.items.topic_links([book.id])

    assert counted == 2
    assert [t.id for t in left] == [keep.id]
    assert [link.topic_id for link in links[book.id]] == [keep.id]


async def test_collections_listed_by_position_and_published_filter(
    uow_factory: UowFactory,
) -> None:
    """LIB-4: public lists show only published collections."""
    late = make_collection("Summer", position=2)
    early = make_collection("Classics", position=1)
    draft = make_collection("Draft", published=False, position=3)
    async with uow_factory() as uow:
        for collection in (late, early, draft):
            await uow.taxonomy.add_collection(collection)
        everything = await uow.taxonomy.collections(published_only=False)
        public = await uow.taxonomy.collections(published_only=True)
        by_slug = await uow.taxonomy.get_collection_by_slug("summer")
        next_position = await uow.taxonomy.next_collection_position()

    assert [c.slug for c in everything] == ["classics", "summer", "draft"]
    assert [c.slug for c in public] == ["classics", "summer"]
    assert by_slug is not None and by_slug.id == late.id
    assert next_position == 4


async def test_collection_update_and_delete(uow_factory: UowFactory) -> None:
    """LIB-4: titles, cover and flag are updated; delete removes the item rows."""
    collection = make_collection("Classics")
    cover = new_id()
    async with uow_factory() as uow:
        await uow.taxonomy.add_collection(collection)
        collection.title = {"uz": "Klassika", "ru": "", "en": ""}
        collection.cover_file_id = cover
        collection.published = False
        await uow.taxonomy.save_collection(collection)
        loaded = await uow.taxonomy.get_collection(collection.id)
        await uow.taxonomy.set_collection_items(collection.id, [new_id()])
        await uow.taxonomy.delete_collection(collection.id)
        gone = await uow.taxonomy.get_collection(collection.id)
        rows = await uow.taxonomy.collection_item_ids([collection.id])

    assert loaded is not None
    assert loaded.title["uz"] == "Klassika"
    assert loaded.cover_file_id == cover
    assert not loaded.published
    assert gone is None
    assert rows == {}


async def test_collection_items_keep_the_order_and_replace_atomically(
    uow_factory: UowFactory,
) -> None:
    """LIB-4: set_collection_items replaces; duplicates are stored once."""
    collection = make_collection()
    a, b, c = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.taxonomy.add_collection(collection)
        await uow.taxonomy.set_collection_items(collection.id, [c, a, b, a])
        first = await uow.taxonomy.collection_item_ids([collection.id])
        await uow.taxonomy.set_collection_items(collection.id, [b])
        second = await uow.taxonomy.collection_item_ids([collection.id])

    assert first[collection.id] == [c, a, b]
    assert second[collection.id] == [b]
