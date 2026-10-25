"""LIB-5, LIB-7, LIB-12: the UniLibrary search box (not stored, cached upstream)."""

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import replace
from uuid import UUID

from app.modules.library.application.external.search_external import SearchQuery
from app.modules.library.application.external.views import ExternalSearchResult
from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import (
    ExternalAccess,
    ItemKind,
    ItemStatus,
    ItemType,
    ShelfState,
)
from app.modules.library.domain.errors import (
    ExternalDisabledError,
    ExternalUnavailableError,
    LibraryRateLimitedError,
)
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.domain.reader_shelf import ShelfEntry
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_core import LibraryCore
from app.modules.library.wiring_external import ExternalServices, build_external
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import NOW, make_external
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.external_catalog import FakeExternalCatalog, make_record

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


def query(**fields: object) -> SearchQuery:
    """A search with the given fields (defaults: everything unset, page 1)."""
    return SearchQuery(**fields)  # type: ignore[arg-type]


async def search(
    external: ExternalServices, actor: Actor, **fields: object
) -> ExternalSearchResult:
    """Run the search as the actor."""
    return await external.search.execute(actor, query(**fields))


async def test_records_become_cards_that_are_not_stored(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: a card has no id or slug until a user pins the record."""
    catalog.add(make_record("355186"))

    result = await search(external, student, q="elektronika")

    (card,) = result.items
    assert card.id is None and card.slug is None
    assert card.kind is ItemKind.EXTERNAL
    assert card.type is ItemType.TEXTBOOK
    assert card.title == "Elektronika va sxemalar 1"
    assert card.author_label == "SH.K.Ismailov"
    assert card.language == "uz_latn"
    assert card.year_published == 2021
    assert card.cover_url == "https://api.unilibrary.uz/storage/355186.png"
    assert card.description_excerpt == "Elektron sxemalar asoslari."
    assert card.tag_source == "unilibrary"
    assert card.tag_label == "UniLibrary"
    assert card.has_text is False
    assert card.shelf_state is None and card.progress_percent is None
    assert card.external is not None
    assert card.external.external_id == "355186"
    assert card.external.category == 1
    assert card.external.access is ExternalAccess.OPEN
    assert card.external.type_name == "Darslik"
    assert card.external.field_name == "Fizika"
    assert card.external.view_url == "https://unilibrary.uz/literature/355186"
    assert card.external.gone is False


async def test_result_carries_page_total_and_stale(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `{items, page, total, stale}`."""
    for n in range(25):
        catalog.add(make_record(str(1000 + n), title=f"Fizika {n}"))
    catalog.stale = True

    result = await search(external, student, q="fizika", page=2)

    assert result.page == 2
    assert result.total == 25
    assert result.stale is True
    assert len(result.items) == 5  # 20 per page


async def test_filters_reach_the_catalogue(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-5: field, type, language and access are passed on."""
    await search(
        external,
        student,
        q="fizika",
        field_id=27,
        type_id=9,
        language="26",
        access=ExternalAccess.PARTIAL,
    )

    params = catalog.search_calls[0]
    assert params.q == "fizika"
    assert (params.field_id, params.type_id) == (27, 9)
    assert params.language_id == 26
    assert params.access is ExternalAccess.PARTIAL
    assert params.language == "en"  # names in the user's language
    assert params.category == 1


async def test_language_codes_become_unilibrary_ids(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-5: `uz_latn` is Uzbek (id 2); the box may also send a raw id."""
    await search(external, student, language="uz_latn")

    assert catalog.search_calls[0].language_id == 2


async def test_a_subject_searches_its_mapped_field(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    academic: FakeAcademicDirectory,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: `subject_id` goes through `external_field_map`."""
    physics = academic.add_subject(new_id(), "Physics")
    async with uow_factory() as uow:
        await uow.external.replace_field_map(
            [FieldMapEntry(physics, 35), FieldMapEntry(physics, 27)]
        )
        await uow.commit()

    await search(external, student, subject_id=physics)

    assert catalog.search_calls[0].field_id == 27  # the first mapped field


async def test_a_subject_without_a_mapping_finds_nothing_and_asks_nobody(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: no mapped field, no results, no request."""
    result = await search(external, student, subject_id=new_id())

    assert result.items == () and result.total == 0
    assert catalog.calls == 0


async def test_cards_of_unstored_records_show_the_mapped_subject(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    academic: FakeAcademicDirectory,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: the field of a record is a subject chip through the map."""
    physics = academic.add_subject(new_id(), "Physics")
    async with uow_factory() as uow:
        await uow.external.replace_field_map([FieldMapEntry(physics, 27)])
        await uow.commit()
    catalog.add(make_record("1", field_id=27))
    catalog.add(make_record("2", title="Other", field_id=99))

    result = await search(external, student)

    by_id = {c.external.external_id: c for c in result.items if c.external}
    assert [(s.id, s.name) for s in by_id["1"].subjects] == [(physics, "Physics")]
    assert by_id["2"].subjects == ()


async def test_a_pinned_record_shows_its_id_and_the_viewers_shelf(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-7: pinned records come back with the item id and the shelf state."""
    pinned = await store_item(make_external(external_id="355186"))
    catalog.add(make_record("355186"))
    catalog.add(make_record("896986", title="Kvant"))
    async with uow_factory() as uow:
        await uow.shelf.save(
            ShelfEntry(student.user_id, pinned.id, ShelfState.READING, None, NOW, NOW)
        )
        await uow.commit()

    result = await search(external, student)

    by_external = {c.external.external_id: c for c in result.items if c.external}
    assert by_external["355186"].id == pinned.id
    assert by_external["355186"].slug == pinned.slug
    assert by_external["355186"].shelf_state is ShelfState.READING
    assert by_external["896986"].id is None


async def test_a_record_a_librarian_hid_is_left_out(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    librarian: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: hidden records stay hidden for readers, not for librarians."""
    await store_item(make_external(external_id="1", status=ItemStatus.UNPUBLISHED))
    catalog.add(make_record("1"))
    catalog.add(make_record("2", title="Visible"))

    for_student = await search(external, student)
    for_librarian = await search(external, librarian)

    assert [c.external.external_id for c in for_student.items if c.external] == ["2"]
    assert len(for_librarian.items) == 2


async def test_a_pinned_record_shows_its_own_tags_not_the_map(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    academic: FakeAcademicDirectory,
    store_item: StoreItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-12: our overlay (subject tags) is never overwritten by the source."""
    maths = academic.add_subject(new_id(), "Mathematics")
    item = await store_item(make_external(external_id="355186"))
    async with uow_factory() as uow:
        await uow.items.set_subject_links(item.id, [SubjectLink(maths)])
        await uow.commit()
    catalog.add(make_record("355186", field_id=27))

    result = await search(external, student)

    assert [s.name for s in result.items[0].subjects] == ["Mathematics"]


async def test_the_per_user_limit_is_thirty_a_minute(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    other_student: Actor,
) -> None:
    """LIB-12: the 31st search of a minute is rate limited."""
    for _ in range(30):
        await search(external, student)

    with pytest.raises(LibraryRateLimitedError) as caught:
        await search(external, student)

    assert caught.value.params["action"] == "search"
    assert caught.value.params["limit"] == 30
    assert "resets_at" in caught.value.params
    await search(external, other_student)  # another person is not affected


async def test_the_limit_comes_from_settings(
    ext_core: LibraryCore, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: `unilibrary_user_searches_per_min`."""
    tight = replace(
        ext_core,
        settings=LibrarySettings(
            unilibrary_enabled=True, unilibrary_user_searches_per_min=1
        ),
    )
    external = build_external(tight, catalog=catalog)
    await search(external, student)

    with pytest.raises(LibraryRateLimitedError):
        await search(external, student)


async def test_switched_off_answers_not_found_and_calls_nothing(
    external_off: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: the flag is off by default."""
    with pytest.raises(ExternalDisabledError):
        await search(external_off, student)

    assert catalog.calls == 0


async def test_unavailable_source_is_reported_as_unavailable(
    external: ExternalServices, catalog: FakeExternalCatalog, student: Actor
) -> None:
    """LIB-12: nothing cached, breaker open: 503 with `retry_after`."""
    catalog.unavailable(60)

    with pytest.raises(ExternalUnavailableError) as caught:
        await search(external, student)

    assert caught.value.params["retry_after"] == 60


async def test_a_gone_stored_record_is_not_a_search_result_twice(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-12: a record both stored and returned appears once."""
    gone_at = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    stored = make_external(external_id="5")
    assert stored.external is not None
    stored.external.gone_at = gone_at
    await store_item(stored)
    catalog.add(make_record("5"))

    result = await search(external, student)

    assert len(result.items) == 1
    assert isinstance(result.items[0].id, UUID)
    assert result.items[0].external is not None and result.items[0].external.gone
