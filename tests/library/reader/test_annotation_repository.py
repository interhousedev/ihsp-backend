"""LIB-8: SQL annotations are scoped to their owner and soft-deleted."""

import dataclasses
import datetime as dt
from uuid import UUID

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.domain.reader_annotation import (
    Annotation,
    build_annotation,
    soft_delete,
)
from app.modules.library.ports.annotation_repository import (
    AnnotationCursor,
    AnnotationFilter,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def note(
    user_id: UUID,
    item_id: UUID | None = None,
    *,
    minutes: int = 0,
    quote: str | None = "Newton",
    text: str | None = None,
    kind: AnnotationKind = AnnotationKind.HIGHLIGHT,
    color: AnnotationColor = AnnotationColor.YELLOW,
    client_id: UUID | None = None,
) -> Annotation:
    """An annotation created `minutes` after NOW."""
    return build_annotation(
        user_id=user_id,
        item_id=item_id or new_id(),
        file_id=new_id(),
        kind=kind,
        locator={"page": 3},
        quote=quote,
        note=text,
        color=color,
        client_id=client_id or new_id(),
        now=NOW + dt.timedelta(minutes=minutes),
    )


async def test_add_then_read_back_by_id_and_client_id(uow_factory: UowFactory) -> None:
    """LIB-8: the stored annotation keeps its locator, quote and colour."""
    user = new_id()
    saved = note(user, text="remember", color=AnnotationColor.PINK)
    async with uow_factory() as uow:
        await uow.annotations.add(saved)

        by_id = await uow.annotations.get(user, saved.id)
        by_client = await uow.annotations.get_by_client_id(user, saved.client_id)

    assert by_id == by_client
    assert by_id is not None
    assert by_id.locator == {"page": 3}
    assert by_id.note == "remember"
    assert by_id.color is AnnotationColor.PINK
    assert by_id.created_at == saved.created_at


async def test_other_users_never_see_the_annotation(uow_factory: UowFactory) -> None:
    """LIB-16: every lookup is scoped to the owner."""
    owner, stranger = new_id(), new_id()
    saved = note(owner)
    async with uow_factory() as uow:
        await uow.annotations.add(saved)

        assert await uow.annotations.get(stranger, saved.id) is None
        assert await uow.annotations.get_by_client_id(stranger, saved.client_id) is None
        assert await uow.annotations.find_any(stranger, [saved.id]) == []
        assert (
            await uow.annotations.list_page(
                stranger, filters=AnnotationFilter(), after=None, limit=10
            )
            == []
        )
        assert await uow.annotations.list_for_item(stranger, saved.item_id) == []
        assert await uow.annotations.list_for_user(stranger, item_id=None) == []


async def test_soft_deleted_annotation_is_hidden_but_found_by_client_id(
    uow_factory: UowFactory,
) -> None:
    """LIB-9: a replayed create must not bring a deleted annotation back."""
    user, item = new_id(), new_id()
    saved = note(user, item)
    async with uow_factory() as uow:
        await uow.annotations.add(saved)
        await uow.annotations.save(soft_delete(saved, now=NOW))

        assert await uow.annotations.get(user, saved.id) is None
        found = await uow.annotations.get_by_client_id(user, saved.client_id)
        listed = await uow.annotations.list_page(
            user, filters=AnnotationFilter(), after=None, limit=10
        )
        for_item = await uow.annotations.list_for_item(user, item)

    assert found is not None and found.deleted_at == NOW
    assert listed == [] and for_item == []


async def test_find_any_matches_the_id_or_the_client_id(
    uow_factory: UowFactory,
) -> None:
    """LIB-9: a device that never synced a note deletes it by `client_id`."""
    user = new_id()
    first, second = note(user), note(user)
    async with uow_factory() as uow:
        await uow.annotations.add(first)
        await uow.annotations.add(second)

        found = await uow.annotations.find_any(user, [first.id, second.client_id])

    assert {a.id for a in found} == {first.id, second.id}


async def test_list_page_filters_and_pages_newest_first(
    uow_factory: UowFactory,
) -> None:
    """LIB-8: filter by item, kind, colour and text; page by `updated_at`."""
    user, item = new_id(), new_id()
    first = note(user, item, minutes=1, quote="Force equals mass times acceleration")
    second = note(
        user,
        item,
        minutes=2,
        kind=AnnotationKind.NOTE,
        quote=None,
        text="Ask about 50%",
    )
    third = note(user, item, minutes=3, color=AnnotationColor.GREEN)
    elsewhere = note(user, minutes=4)
    async with uow_factory() as uow:
        for saved in (first, second, third, elsewhere):
            await uow.annotations.add(saved)

        everything = await uow.annotations.list_page(
            user, filters=AnnotationFilter(), after=None, limit=10
        )
        page = await uow.annotations.list_page(
            user, filters=AnnotationFilter(item_id=item), after=None, limit=2
        )
        rest = await uow.annotations.list_page(
            user,
            filters=AnnotationFilter(item_id=item),
            after=AnnotationCursor(page[-1].updated_at, page[-1].id),
            limit=2,
        )
        notes = await uow.annotations.list_page(
            user,
            filters=AnnotationFilter(kind=AnnotationKind.NOTE),
            after=None,
            limit=10,
        )
        green = await uow.annotations.list_page(
            user,
            filters=AnnotationFilter(color=AnnotationColor.GREEN),
            after=None,
            limit=10,
        )
        text = await uow.annotations.list_page(
            user, filters=AnnotationFilter(query="50%"), after=None, limit=10
        )
        quote = await uow.annotations.list_page(
            user, filters=AnnotationFilter(query="MASS times"), after=None, limit=10
        )

    assert [a.id for a in everything] == [
        elsewhere.id,
        third.id,
        second.id,
        first.id,
    ]
    assert [a.id for a in page] == [third.id, second.id]
    assert [a.id for a in rest] == [first.id]
    assert [a.id for a in notes] == [second.id]
    assert [a.id for a in green] == [third.id]
    assert [a.id for a in text] == [second.id]
    assert [a.id for a in quote] == [first.id]


async def test_search_text_is_not_a_like_pattern(uow_factory: UowFactory) -> None:
    """LIB-8: `%` and `_` in the search box are plain characters."""
    user = new_id()
    percent = note(user, quote="100% sure")
    other = note(user, quote="nothing here")
    async with uow_factory() as uow:
        await uow.annotations.add(percent)
        await uow.annotations.add(other)

        rows = await uow.annotations.list_page(
            user, filters=AnnotationFilter(query="%"), after=None, limit=10
        )

    assert [a.id for a in rows] == [percent.id]


async def test_list_for_item_is_oldest_first_and_list_for_user_can_narrow(
    uow_factory: UowFactory,
) -> None:
    """LIB-10: the notebook reads notes in the order they were taken."""
    user, item = new_id(), new_id()
    late = note(user, item, minutes=9)
    early = note(user, item, minutes=1)
    other_item = note(user, minutes=5)
    async with uow_factory() as uow:
        for saved in (late, early, other_item):
            await uow.annotations.add(saved)

        for_item = await uow.annotations.list_for_item(user, item)
        everything = await uow.annotations.list_for_user(user, item_id=None)
        narrowed = await uow.annotations.list_for_user(user, item_id=item)

    assert [a.id for a in for_item] == [early.id, late.id]
    assert [a.id for a in everything] == [early.id, other_item.id, late.id]
    assert [a.id for a in narrowed] == [early.id, late.id]


async def test_save_updates_note_and_colour(uow_factory: UowFactory) -> None:
    """LIB-8: an edited annotation keeps its quote and locator."""
    user = new_id()
    saved = note(user)
    async with uow_factory() as uow:
        await uow.annotations.add(saved)
        await uow.annotations.save(
            dataclasses.replace(
                saved,
                note="new note",
                color=AnnotationColor.BLUE,
                updated_at=NOW + dt.timedelta(minutes=9),
            )
        )

        loaded = await uow.annotations.get(user, saved.id)

    assert loaded is not None
    assert loaded.note == "new note"
    assert loaded.color is AnnotationColor.BLUE
    assert loaded.quote == saved.quote
    assert loaded.updated_at == NOW + dt.timedelta(minutes=9)


async def test_delete_all_removes_every_annotation_of_the_user(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: annotations die with the account, deleted ones included."""
    leaving, staying = new_id(), new_id()
    gone = note(leaving)
    async with uow_factory() as uow:
        await uow.annotations.add(gone)
        await uow.annotations.save(soft_delete(gone, now=NOW))
        await uow.annotations.add(note(leaving))
        await uow.annotations.add(note(staying))

        removed = await uow.annotations.delete_all(leaving)

        assert removed == 2
        assert await uow.annotations.get_by_client_id(leaving, gone.client_id) is None
        assert len(await uow.annotations.list_for_user(staying, item_id=None)) == 1


async def test_adding_the_same_client_id_twice_keeps_the_first(
    uow_factory: UowFactory,
) -> None:
    """LIB-9: two tabs flushing the same offline queue create one annotation."""
    user, client_id = new_id(), new_id()
    first = note(user, client_id=client_id, text="first")
    async with uow_factory() as uow:
        inserted = await uow.annotations.add(first)
        duplicate = await uow.annotations.add(
            note(user, client_id=client_id, text="second")
        )

        kept = await uow.annotations.get_by_client_id(user, client_id)
        everything = await uow.annotations.list_for_user(user, item_id=None)

    assert (inserted, duplicate) == (True, False)
    assert kept is not None and kept.note == "first"
    assert len(everything) == 1
