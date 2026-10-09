"""LIB-1, LIB-4: items of the three kinds survive a round trip; tags and history."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from app.modules.library.domain.entities import Item, SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    EventKind,
    ExternalSource,
    ItemStatus,
    SubjectRole,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import NOW, make_book, make_external, make_material

StoreItem = Callable[[Item], Awaitable[Item]]


async def test_book_round_trips_with_details_and_files(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-3: rights data and the primary file come back with the item."""
    book = await store_item(make_book(title="Fizika 10"))

    async with uow_factory() as uow:
        loaded = await uow.items.get(book.id)

    assert loaded is not None
    assert book.book is not None
    assert loaded.book is not None and loaded.book.rights == book.book.rights
    assert loaded.primary_file is not None
    assert loaded.primary_file.file_id == book.files[0].file_id
    assert loaded.title == "Fizika 10"


async def test_material_snapshot_and_slug_lookup(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: the uploader snapshot is stored with the material."""
    material = await store_item(make_material())

    async with uow_factory() as uow:
        loaded = await uow.items.get_by_slug(material.slug)

    assert loaded is not None
    assert loaded.material is not None
    assert loaded.material.uploader_name == "Aziza K."
    assert loaded.material.uploader_cohort == "2025"


async def test_external_record_is_found_by_source_and_id(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-12: a pinned UniLibrary record is looked up by its external id."""
    card = await store_item(make_external(external_id="896986"))

    async with uow_factory() as uow:
        loaded = await uow.items.get_by_external(ExternalSource.UNILIBRARY, "896986")
        missing = await uow.items.get_by_external(ExternalSource.UNILIBRARY, "1")

    assert loaded is not None and loaded.id == card.id
    assert loaded.external is not None
    assert loaded.external.view_url.endswith("/literature/896986")
    assert missing is None


async def test_save_updates_status_and_details(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: a status change and a review message persist."""
    material = await store_item(make_material(status=ItemStatus.PENDING_REVIEW))

    async with uow_factory() as uow:
        item = await uow.items.get(material.id, lock=True)
        assert item is not None and item.material is not None
        item.status = ItemStatus.CHANGES_REQUESTED
        item.material.review_message = "Add the title page"
        await uow.items.save(item)
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.items.get(material.id)
    assert loaded is not None and loaded.material is not None
    assert loaded.status is ItemStatus.CHANGES_REQUESTED
    assert loaded.material.review_message == "Add the title page"


async def test_subject_and_topic_tags_are_replaced(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-4: tags are set as a whole; 'any year' comes back as None."""
    book = await store_item(make_book())
    physics, maths = new_id(), new_id()

    async with uow_factory() as uow:
        await uow.items.set_subject_links(
            book.id,
            [
                SubjectLink(physics, SubjectRole.TEXTBOOK, 1),
                SubjectLink(maths),
                SubjectLink(maths),
            ],
        )
        await uow.commit()
    async with uow_factory() as uow:
        await uow.items.set_subject_links(book.id, [SubjectLink(maths)])
        links = await uow.items.subject_links([book.id])

    assert [link.subject_id for link in links[book.id]] == [maths]
    assert links[book.id][0].year_of_study is None
    assert TopicLink(uuid4()).page_from is None


async def test_duplicates_are_found_by_hash(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the same file or text is flagged as a duplicate."""
    first = make_material()
    first.files[0].sha256 = "a" * 64
    first.content_hash = "b" * 64
    await store_item(first)
    second = await store_item(make_material(title="Other"))

    async with uow_factory() as uow:
        by_file = await uow.items.find_by_file_hash("a" * 64, exclude=second.id)
        by_text = await uow.items.find_by_content_hash("b" * 64, exclude=first.id)

    assert by_file == [first.id]
    assert by_text == []


async def test_events_get_consecutive_numbers(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the history of an item is append-only and numbered."""
    material = await store_item(make_material())

    async with uow_factory() as uow:
        await uow.events.append(material.id, EventKind.CREATED, at=NOW)
        await uow.events.append(material.id, EventKind.SUBMITTED, at=NOW)
        events = await uow.events.history(material.id)

    assert [(e.seq, e.kind) for e in events] == [
        (1, EventKind.CREATED),
        (2, EventKind.SUBMITTED),
    ]
