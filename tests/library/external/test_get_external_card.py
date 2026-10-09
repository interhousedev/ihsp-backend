"""LIB-12: the card of one UniLibrary record (stored or not)."""

from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ExternalAccess, ItemStatus, ItemType
from app.modules.library.domain.errors import (
    ExternalDisabledError,
    ExternalUnavailableError,
    ItemNotFoundError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from tests.factories.library import make_external
from tests.fakes.library.external_catalog import (
    FakeExternalCatalog,
    make_detail,
    make_record,
)

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


async def test_an_unstored_record_is_shown_from_the_detail_call(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `GET /{external_id}` is the card of the record, not stored."""
    catalog.add(make_record("355186"), make_detail("355186"))

    card = await external.get_card.execute(student, "355186", category=1)

    assert card.id is None and card.slug is None
    assert card.title == "Elektronika va sxemalar 1"
    assert card.page_count == 288  # only the detail has it
    assert card.external is not None and card.external.external_id == "355186"
    assert catalog.get_calls == [("355186", 1, "en")]


async def test_a_pinned_record_answers_with_the_stored_card(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-7: the stored item's id and slug come back."""
    stored = await store_item(make_external(external_id="355186"))
    catalog.add(make_record("355186"))

    card = await external.get_card.execute(student, "355186", category=1)

    assert card.id == stored.id and card.slug == stored.slug


async def test_a_missing_unstored_record_is_not_found(
    external: ExternalServices, student: Actor
) -> None:
    """LIB-12: UniLibrary answered `{"result": []}` and we hold nothing."""
    with pytest.raises(ItemNotFoundError):
        await external.get_card.execute(student, "404", category=1)


async def test_a_stored_record_that_is_gone_upstream_is_marked_gone(
    external: ExternalServices,
    student: Actor,
    store_item: StoreItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: `gone`: kept for shelves as "no longer available"."""
    stored = await store_item(make_external(external_id="77001"))

    card = await external.get_card.execute(student, "77001", category=1)

    assert card.id == stored.id
    assert card.external is not None and card.external.gone is True
    async with uow_factory() as uow:
        loaded = await uow.items.get(stored.id)
    assert loaded is not None and loaded.external is not None
    assert loaded.external.gone_at is not None
    assert loaded.status is ItemStatus.PUBLISHED


async def test_a_record_that_came_back_is_no_longer_gone(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: the mark is lifted when UniLibrary has the record again."""
    stored = make_external(external_id="5")
    assert stored.external is not None
    stored.external.gone_at = stored.created_at
    await store_item(stored)
    catalog.add(make_record("5"))

    card = await external.get_card.execute(student, "5", category=1)

    assert card.external is not None and card.external.gone is False
    async with uow_factory() as uow:
        loaded = await uow.items.get(stored.id)
    assert loaded is not None and loaded.external is not None
    assert loaded.external.gone_at is None


async def test_a_stored_record_is_served_while_the_source_is_down(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: pinned records keep working from their snapshot."""
    stored = await store_item(make_external(external_id="355186"))
    catalog.unavailable()

    card = await external.get_card.execute(student, "355186", category=1)

    assert card.id == stored.id
    assert card.title == stored.title


async def test_an_unstored_record_is_unavailable_while_the_source_is_down(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: nothing to fall back on."""
    catalog.unavailable()

    with pytest.raises(ExternalUnavailableError):
        await external.get_card.execute(student, "1", category=1)


async def test_a_hidden_record_is_not_found_for_readers(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    librarian: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: a librarian can hide a record; readers get a plain 404."""
    stored = await store_item(
        make_external(external_id="9", status=ItemStatus.UNPUBLISHED)
    )
    catalog.add(make_record("9"))

    with pytest.raises(ItemNotFoundError):
        await external.get_card.execute(student, "9", category=1)
    card = await external.get_card.execute(librarian, "9", category=1)
    assert card.id == stored.id
    assert catalog.get_calls == [("9", 1, "en")]  # only the librarian's call


async def test_the_category_picks_the_link(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: a dissertation is asked as category 3."""
    catalog.add(
        make_record("8", category=3, item_type=ItemType.OTHER),
        make_detail("8", category=3, item_type=ItemType.OTHER),
    )

    card = await external.get_card.execute(student, "8", category=3)

    assert card.external is not None
    assert card.external.view_url == "https://unilibrary.uz/dissertation/8"
    assert card.external.category == 3
    assert card.external.access is ExternalAccess.OPEN


async def test_switched_off_answers_not_found_and_calls_nothing(
    external_off: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: flag off."""
    with pytest.raises(ExternalDisabledError):
        await external_off.get_card.execute(student, "1", category=1)

    assert catalog.calls == 0
