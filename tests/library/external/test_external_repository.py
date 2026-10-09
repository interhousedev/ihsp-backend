"""LIB-12: feeds, the field map and lookups of stored UniLibrary records."""

import datetime as dt
from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ExternalAccess,
    ExternalSource,
    ItemKind,
    ItemStatus,
    Visibility,
)
from app.modules.library.domain.external_feed import (
    Feed,
    FeedParams,
    FieldMapEntry,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import NOW, make_book, make_external

StoreItem = Callable[[Item], Awaitable[Item]]
LATER = NOW + dt.timedelta(hours=1)


def make_feed(name: str = "Physics", *, at: dt.datetime = NOW) -> Feed:
    """A feed with a few filters."""
    return Feed(
        id=new_id(),
        name=name,
        params=FeedParams(
            category=1,
            field_ids=[27],
            type_ids=[9, 2],
            language_ids=[2, 26],
            access=[ExternalAccess.OPEN, ExternalAccess.PARTIAL],
        ),
        max_items=500,
        created_at=at,
        updated_at=at,
    )


# - - - Feeds - - -


async def test_feed_round_trips_with_its_params(uow_factory: UowFactory) -> None:
    """LIB-12: the feed and its filters come back as stored."""
    feed = make_feed()
    async with uow_factory() as uow:
        await uow.external.add_feed(feed)
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.external.get_feed(feed.id)

    assert loaded is not None
    assert loaded.name == "Physics"
    assert loaded.params == feed.params
    assert loaded.max_items == 500
    assert loaded.enabled is False
    assert loaded.estimate is None
    assert loaded.source is ExternalSource.UNILIBRARY


async def test_unknown_feed_is_none(uow_factory: UowFactory) -> None:
    """LIB-12: lookup of a missing feed."""
    async with uow_factory() as uow:
        assert await uow.external.get_feed(new_id()) is None


async def test_feeds_are_listed_oldest_first(uow_factory: UowFactory) -> None:
    """LIB-12: stable order for the admin table."""
    second = make_feed("Second", at=LATER)
    first = make_feed("First", at=NOW)
    async with uow_factory() as uow:
        await uow.external.add_feed(second)
        await uow.external.add_feed(first)
        await uow.commit()

    async with uow_factory() as uow:
        names = [f.name for f in await uow.external.list_feeds()]

    assert names == ["First", "Second"]


async def test_saving_a_feed_updates_it(uow_factory: UowFactory) -> None:
    """LIB-12: rename, change filters, switch on."""
    feed = make_feed()
    async with uow_factory() as uow:
        await uow.external.add_feed(feed)
        await uow.commit()

    feed.name = "Physics and maths"
    feed.enabled = True
    feed.estimate = 411
    feed.params = FeedParams(field_ids=[27, 25])
    async with uow_factory() as uow:
        await uow.external.save_feed(feed)
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.external.get_feed(feed.id)
    assert loaded is not None
    assert (loaded.name, loaded.enabled, loaded.estimate) == (
        "Physics and maths",
        True,
        411,
    )
    assert loaded.params.field_ids == [27, 25]


async def test_a_feed_can_be_deleted_once(uow_factory: UowFactory) -> None:
    """LIB-12: delete answers whether something was removed."""
    feed = make_feed()
    async with uow_factory() as uow:
        await uow.external.add_feed(feed)
        await uow.commit()

    async with uow_factory() as uow:
        first = await uow.external.delete_feed(feed.id)
        second = await uow.external.delete_feed(feed.id)
        await uow.commit()

    assert (first, second) == (True, False)


# - - - Field map - - -


async def test_field_map_is_replaced_as_a_whole(uow_factory: UowFactory) -> None:
    """LIB-12: the PUT replaces the table."""
    physics, maths, chemistry = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.external.replace_field_map(
            [FieldMapEntry(physics, 27), FieldMapEntry(maths, 25)]
        )
        await uow.commit()

    async with uow_factory() as uow:
        await uow.external.replace_field_map(
            [FieldMapEntry(maths, 25), FieldMapEntry(chemistry, 29)]
        )
        await uow.commit()

    async with uow_factory() as uow:
        entries = await uow.external.field_map()
    assert {(e.subject_id, e.external_field_id) for e in entries} == {
        (maths, 25),
        (chemistry, 29),
    }


async def test_a_subject_may_map_to_several_fields(uow_factory: UowFactory) -> None:
    """LIB-12: the key is (subject, source, field)."""
    subject = new_id()
    async with uow_factory() as uow:
        await uow.external.replace_field_map(
            [FieldMapEntry(subject, 27), FieldMapEntry(subject, 35)]
        )
        await uow.commit()

    async with uow_factory() as uow:
        entries = await uow.external.field_map()

    assert sorted(e.external_field_id for e in entries) == [27, 35]


async def test_an_empty_replace_clears_the_map(uow_factory: UowFactory) -> None:
    """LIB-12: no entries means no mapping."""
    async with uow_factory() as uow:
        await uow.external.replace_field_map([FieldMapEntry(new_id(), 27)])
        await uow.commit()
    async with uow_factory() as uow:
        await uow.external.replace_field_map([])
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.external.field_map() == []


# - - - Stored records - - -


async def test_stored_records_are_found_by_external_id(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-12: which of these UniLibrary ids are already pinned?"""
    pinned = await store_item(make_external(external_id="355186"))
    other = await store_item(make_external(title="Other", external_id="896986"))

    async with uow_factory() as uow:
        found = await uow.external.item_ids_by_external(
            ExternalSource.UNILIBRARY, ["355186", "896986", "111"]
        )

    assert found == {"355186": pinned.id, "896986": other.id}


async def test_lookup_of_no_ids_is_empty(uow_factory: UowFactory) -> None:
    """LIB-12: nothing asked, nothing found."""
    async with uow_factory() as uow:
        assert (
            await uow.external.item_ids_by_external(ExternalSource.UNILIBRARY, []) == {}
        )


async def test_hidden_records_are_unpublished_or_hidden_external_items(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-12: the admin list of hidden records; books and visible ones stay out."""
    unpublished = await store_item(
        make_external(external_id="1", status=ItemStatus.UNPUBLISHED)
    )
    hidden = await store_item(
        make_external(external_id="2", visibility=Visibility.HIDDEN)
    )
    await store_item(make_external(external_id="3"))
    book = await store_item(make_book(status=ItemStatus.UNPUBLISHED))
    assert book.kind is ItemKind.BOOK

    async with uow_factory() as uow:
        ids = await uow.external.hidden_item_ids(limit=50)

    assert set(ids) == {unpublished.id, hidden.id}
