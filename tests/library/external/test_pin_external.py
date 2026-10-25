"""LIB-7, LIB-12: pinning a UniLibrary record stores a link-only snapshot."""

import hashlib
import json
from collections.abc import Awaitable, Callable

from app.modules.library.application.external.snapshot import (
    snapshot_hash,
    snapshot_of,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    EventKind,
    ExternalAccess,
    ExternalSource,
    ItemKind,
    ItemLanguage,
    ItemStatus,
    ItemType,
    Visibility,
)
from app.modules.library.domain.errors import (
    ExternalDisabledError,
    ExternalUnavailableError,
    ItemNotFoundError,
)
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import make_external
from tests.fakes.clock import FixedClock
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.external_catalog import (
    FakeExternalCatalog,
    make_detail,
    make_record,
)

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


async def stored_item(uow_factory: UowFactory, external_id: str) -> Item:
    """The stored item of a UniLibrary record."""
    async with uow_factory() as uow:
        item = await uow.items.get_by_external(ExternalSource.UNILIBRARY, external_id)
    assert item is not None
    return item


async def test_pin_stores_a_published_lyceum_link_item(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-12: kind external, published, visible to the lyceum, no owner."""
    catalog.add(make_record("355186"), make_detail("355186"))

    result = await external.pin.execute(student, "355186", category=1)

    assert result.created is True
    item = await stored_item(uow_factory, "355186")
    assert item.id == result.card.id
    assert item.kind is ItemKind.EXTERNAL
    assert item.status is ItemStatus.PUBLISHED
    assert item.visibility is Visibility.LYCEUM
    assert item.owner_id is None
    assert item.created_by == student.user_id
    assert item.files == [] and item.cover_file_id is None
    assert item.published_at == clock.now()


async def test_pin_copies_the_facts_of_the_record(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: title, authors, year, publisher, ISBN, pages, cover link, type."""
    catalog.add(make_record("355186"), make_detail("355186"))

    await external.pin.execute(student, "355186", category=1)

    item = await stored_item(uow_factory, "355186")
    assert item.title == "Elektronika va sxemalar 1"
    assert item.type is ItemType.TEXTBOOK
    assert item.language is ItemLanguage.UZ_LATN
    assert item.author_label == "SH.K.Ismailov"
    assert item.authors == ["SH.K.Ismailov"]
    assert item.year_published == 2021
    assert item.publisher == "Toshkent"
    assert item.isbn == "978-9943-00-111-1"
    assert item.page_count == 288
    assert item.description == "Elektron sxemalar asoslari."
    assert item.cover_url == "https://api.unilibrary.uz/storage/355186.png"
    assert item.has_text is False and item.download_allowed is False
    assert "elektronika" in item.search_text
    assert item.slug.startswith("elektronika-va-sxemalar-1-")


async def test_pin_keeps_the_external_details_as_a_snapshot(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-12: `external_details` with names, link, snapshot and its hash."""
    catalog.add(
        make_record("355186"), make_detail("355186", access=ExternalAccess.PARTIAL)
    )

    await external.pin.execute(student, "355186", category=1)

    details = (await stored_item(uow_factory, "355186")).external
    assert details is not None
    assert details.source is ExternalSource.UNILIBRARY
    assert details.category == 1
    assert details.access is ExternalAccess.PARTIAL
    assert details.view_url == "https://unilibrary.uz/literature/355186"
    assert details.type_name == {"en": "Darslik"}
    assert details.field_name == {"en": "Fizika"}
    assert details.language_name == {"en": "O'zbek"}
    assert details.fetched_at == clock.now()
    assert details.detail_fetched_at == clock.now()
    assert details.gone_at is None
    assert details.snapshot["keywords"] == ["elektronika", "sxema"]
    assert details.snapshot["isbn"] == "978-9943-00-111-1"
    assert details.snapshot["title"] == "Elektronika va sxemalar 1"


async def test_snapshot_hash_is_sha256_of_the_canonical_snapshot(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: same facts, same hash; the hash is over sorted compact JSON."""
    catalog.add(make_record("355186"), make_detail("355186"))
    await external.pin.execute(student, "355186", category=1)

    details = (await stored_item(uow_factory, "355186")).external

    assert details is not None
    canonical = json.dumps(
        details.snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    assert details.snapshot_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert len(details.snapshot_hash) == 64


def test_views_do_not_change_the_snapshot_hash() -> None:
    """LIB-12: view counts move all the time and are not facts of the record."""
    first = make_detail("1", views=1)
    second = make_detail("1", views=900)

    assert snapshot_hash(snapshot_of(first)) == snapshot_hash(snapshot_of(second))


def test_a_changed_fact_changes_the_snapshot_hash() -> None:
    """LIB-12: the hash tells a sync that the record changed."""
    before = make_detail("1")
    after = make_detail("1", title="Elektronika va sxemalar 2")

    assert snapshot_hash(snapshot_of(before)) != snapshot_hash(snapshot_of(after))


async def test_pin_returns_the_card_with_the_item_id(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: the card now has `id` and `slug`."""
    catalog.add(make_record("355186"), make_detail("355186"))

    result = await external.pin.execute(student, "355186", category=1)

    assert result.card.id is not None and result.card.slug is not None
    assert result.card.external is not None
    assert result.card.external.external_id == "355186"
    assert result.card.page_count == 288


async def test_pin_is_idempotent(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    other_student: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: the second pin, by anyone, returns the same item."""
    catalog.add(make_record("355186"), make_detail("355186"))

    first = await external.pin.execute(student, "355186", category=1)
    second = await external.pin.execute(student, "355186", category=1)
    third = await external.pin.execute(other_student, "355186", category=1)

    assert (first.created, second.created, third.created) == (True, False, False)
    assert first.card.id == second.card.id == third.card.id
    assert len(catalog.get_calls) == 1  # later pins never ask UniLibrary again
    item = await stored_item(uow_factory, "355186")
    assert item.created_by == student.user_id


async def test_pin_writes_a_history_entry(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: who pinned the record is in the item's history."""
    catalog.add(make_record("355186"), make_detail("355186"))
    result = await external.pin.execute(student, "355186", category=1)
    assert result.card.id is not None

    async with uow_factory() as uow:
        events = await uow.events.history(result.card.id)

    assert [(e.kind, e.actor_id) for e in events] == [
        (EventKind.CREATED, student.user_id)
    ]
    assert events[0].data["source"] == "unilibrary"


async def test_pin_tags_the_item_with_the_mapped_subject(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    academic: FakeAcademicDirectory,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: the field of the record is a subject through the field map."""
    physics = academic.add_subject(new_id(), "Physics")
    async with uow_factory() as uow:
        await uow.external.replace_field_map([FieldMapEntry(physics, 27)])
        await uow.commit()
    catalog.add(make_record("355186", field_id=27), make_detail("355186", field_id=27))

    result = await external.pin.execute(student, "355186", category=1)

    assert [s.name for s in result.card.subjects] == ["Physics"]
    item = await stored_item(uow_factory, "355186")
    async with uow_factory() as uow:
        links = (await uow.items.subject_links([item.id]))[item.id]
    assert [link.subject_id for link in links] == [physics]


async def test_pin_of_a_missing_record_is_not_found(
    external: ExternalServices, student: Actor
) -> None:
    """LIB-12: UniLibrary does not have it, nothing is stored."""
    with pytest.raises(ItemNotFoundError):
        await external.pin.execute(student, "404", category=1)


async def test_pin_needs_the_source_when_the_record_is_not_stored(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: no snapshot can be taken while UniLibrary is down."""
    catalog.unavailable()

    with pytest.raises(ExternalUnavailableError):
        await external.pin.execute(student, "355186", category=1)


async def test_pin_of_a_stored_record_works_while_the_source_is_down(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: an already pinned record needs no request."""
    stored = await store_item(make_external(external_id="355186"))
    catalog.unavailable()

    result = await external.pin.execute(student, "355186", category=1)

    assert result.card.id == stored.id and result.created is False


async def test_pin_of_a_hidden_record_is_not_found_for_readers(
    external: ExternalServices, student: Actor, store_item: StoreItem
) -> None:
    """LIB-12: a hidden record cannot be put on a shelf or in a list."""
    await store_item(make_external(external_id="9", status=ItemStatus.UNPUBLISHED))

    with pytest.raises(ItemNotFoundError):
        await external.pin.execute(student, "9", category=1)


async def test_long_values_are_cut_to_the_columns(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: titles, authors, publisher and ISBN fit the item row."""
    catalog.add(
        make_record("7", title="T" * 400, authors="A" * 400),
        make_detail(
            "7", title="T" * 400, authors="A" * 400, publisher="P" * 400, isbn="9" * 80
        ),
    )

    await external.pin.execute(student, "7", category=1)

    item = await stored_item(uow_factory, "7")
    assert len(item.title) == 255 and item.title.endswith("…")
    assert len(item.author_label) == 255
    assert item.publisher is not None and len(item.publisher) == 255
    assert item.isbn is not None and len(item.isbn) == 32


async def test_switched_off_answers_not_found_and_stores_nothing(
    external_off: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
) -> None:
    """LIB-12: flag off."""
    catalog.add(make_record("1"))

    with pytest.raises(ExternalDisabledError):
        await external_off.pin.execute(student, "1", category=1)

    assert catalog.calls == 0


async def test_a_pin_that_loses_the_race_returns_the_winner(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    other_student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: two people pin at once; one row, both get the same card."""
    winner = make_external(external_id="355186")
    catalog.add(make_record("355186"), make_detail("355186"))

    async def other_pin_first(_external_id: str) -> None:
        await store_item(winner)
        catalog.on_get = None

    catalog.on_get = other_pin_first

    result = await external.pin.execute(student, "355186", category=1)

    assert result.card.id == winner.id
    assert result.created is False
