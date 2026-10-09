"""LIB-8, LIB-9, LIB-16: private annotations, offline sync, export."""

from uuid import UUID

from app.modules.library.application.reader.annotation_data import AnnotationData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import AnnotationColor, AnnotationKind, ItemStatus
from app.modules.library.domain.errors import (
    AnnotationNotFoundError,
    ItemNotFoundError,
    NotSupportedError,
)
from app.modules.library.domain.reader_annotation import MAX_NOTE, MAX_QUOTE
from app.modules.library.domain.reader_errors import (
    FileNotInItemError,
    InvalidAnnotationError,
    InvalidLocatorError,
    SyncTooLargeError,
)
from app.modules.library.ports.annotation_repository import AnnotationFilter
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest


def data(item: Item, **fields: object) -> AnnotationData:
    """A yellow highlight of page 3 of the item's first file."""
    values: dict[str, object] = {
        "client_id": new_id(),
        "item_id": item.id,
        "file_id": item.files[0].file_id,
        "kind": AnnotationKind.HIGHLIGHT,
        "locator": {"page": 3},
        "quote": "A body keeps its state of rest",
        "note": None,
        "color": AnnotationColor.YELLOW,
    }
    values.update(fields)
    return AnnotationData(**values)  # type: ignore[arg-type]


# - - - Creating - - -


async def test_annotation_is_created_for_a_readable_book(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-8: the new annotation carries the quote, the page and the colour."""
    created = await reader.create_annotation.execute(
        student, data(book, note="Newton 1", color=AnnotationColor.GREEN)
    )

    assert created.user_id == student.user_id
    assert created.locator == {"page": 3}
    assert created.quote == "A body keeps its state of rest"
    assert created.note == "Newton 1"
    assert created.color is AnnotationColor.GREEN


async def test_creating_twice_with_the_same_client_id_returns_the_same_annotation(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-9: a retried POST changes nothing."""
    first_input = data(book, note="first")
    first = await reader.create_annotation.execute(student, first_input)

    second = await reader.create_annotation.execute(
        student, data(book, client_id=first_input.client_id, note="other")
    )
    page = await reader.list_annotations.execute(student)

    assert second.id == first.id
    assert second.note == "first"
    assert len(page.items) == 1


async def test_replaying_the_create_of_a_deleted_annotation_is_a_404(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-9: a deleted annotation does not come back through a replay."""
    payload = data(book)
    created = await reader.create_annotation.execute(student, payload)
    await reader.delete_annotation.execute(student, created.id)

    with pytest.raises(AnnotationNotFoundError):
        await reader.create_annotation.execute(student, payload)


async def test_unilibrary_record_cannot_be_annotated(
    reader: ReaderServices, student: Actor, external: Item
) -> None:
    """LIB-12: link-only records answer `library/not-supported`."""
    payload = AnnotationData(
        client_id=new_id(),
        item_id=external.id,
        file_id=new_id(),
        kind=AnnotationKind.BOOKMARK,
        locator={"page": 1},
        quote=None,
        note=None,
        color=AnnotationColor.YELLOW,
    )

    with pytest.raises(NotSupportedError):
        await reader.create_annotation.execute(student, payload)


async def test_item_the_user_cannot_read_is_not_found(
    reader: ReaderServices, student: Actor, taken_down: Item
) -> None:
    """LIB-1: taken-down items take no new notes."""
    with pytest.raises(ItemNotFoundError):
        await reader.create_annotation.execute(student, data(taken_down))


async def test_file_of_another_item_is_refused(
    reader: ReaderServices, student: Actor, book: Item, material: Item
) -> None:
    """LIB-8: the file must belong to the item."""
    with pytest.raises(FileNotInItemError):
        await reader.create_annotation.execute(
            student, data(book, file_id=material.files[0].file_id)
        )


async def test_locator_must_fit_the_format(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-8: a PDF annotation needs a page."""
    with pytest.raises(InvalidLocatorError):
        await reader.create_annotation.execute(
            student, data(book, locator={"cfi": "epubcfi(/6)", "progress": 0.1})
        )


async def test_long_quote_and_note_are_refused(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-8: quote up to 1000 characters, note up to 2000."""
    with pytest.raises(InvalidAnnotationError):
        await reader.create_annotation.execute(
            student, data(book, quote="q" * (MAX_QUOTE + 1))
        )
    with pytest.raises(InvalidAnnotationError):
        await reader.create_annotation.execute(
            student, data(book, note="n" * (MAX_NOTE + 1))
        )


# - - - Sync - - -


async def test_sync_creates_updates_and_deletes_in_one_call(
    reader: ReaderServices, student: Actor, book: Item, clock: FixedClock
) -> None:
    """LIB-9: the offline queue flushes creates, edits and deletes together."""
    keep = data(book, note="draft")
    drop = await reader.create_annotation.execute(student, data(book, quote="old"))
    await reader.create_annotation.execute(student, keep)
    clock.advance(minutes=5)

    fresh = data(book, quote="new")
    edited = data(book, client_id=keep.client_id, note="final", color=AnnotationColor.PINK)
    result = await reader.sync_annotations.execute(
        student, upserts=[fresh, edited], deletes=[drop.id]
    )
    page = await reader.list_annotations.execute(student)

    assert [a.client_id for a in result] == [fresh.client_id, keep.client_id]
    assert result[1].note == "final" and result[1].color is AnnotationColor.PINK
    assert {a.client_id for a in page.items} == {fresh.client_id, keep.client_id}


async def test_sync_deletes_by_client_id_of_a_note_the_server_never_saw(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-9: created and deleted offline, the device only knows the client id."""
    payload = data(book)

    result = await reader.sync_annotations.execute(
        student, upserts=[payload], deletes=[payload.client_id]
    )
    page = await reader.list_annotations.execute(student)

    assert result == []
    assert page.items == []


async def test_sync_replay_does_not_bring_back_a_deleted_annotation(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-9: syncing the same queue twice is safe."""
    payload = data(book)
    first = await reader.sync_annotations.execute(student, upserts=[payload], deletes=[])
    await reader.delete_annotation.execute(student, first[0].id)

    again = await reader.sync_annotations.execute(student, upserts=[payload], deletes=[])

    assert again == []
    assert (await reader.list_annotations.execute(student)).items == []


async def test_sync_ignores_deletes_of_unknown_or_foreign_ids(
    reader: ReaderServices, student: Actor, other_student: Actor, book: Item
) -> None:
    """LIB-16: a delete never touches another user's note."""
    theirs = await reader.create_annotation.execute(other_student, data(book))

    await reader.sync_annotations.execute(
        student, upserts=[], deletes=[theirs.id, theirs.client_id, new_id()]
    )

    assert len((await reader.list_annotations.execute(other_student)).items) == 1


async def test_sync_accepts_at_most_200_changes(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-9: 200 changes pass, 201 are refused."""
    upserts = [data(book) for _ in range(200)]
    await reader.sync_annotations.execute(student, upserts=upserts, deletes=[])

    with pytest.raises(SyncTooLargeError):
        await reader.sync_annotations.execute(
            student, upserts=upserts[:200], deletes=[new_id()]
        )


async def test_one_bad_change_rolls_the_whole_sync_back(
    reader: ReaderServices, student: Actor, book: Item, external: Item
) -> None:
    """LIB-9: the queue is applied entirely or not at all."""
    good = data(book)
    bad = AnnotationData(
        client_id=new_id(),
        item_id=external.id,
        file_id=new_id(),
        kind=AnnotationKind.BOOKMARK,
        locator={"page": 1},
        quote=None,
        note=None,
        color=AnnotationColor.YELLOW,
    )

    with pytest.raises(NotSupportedError):
        await reader.sync_annotations.execute(student, upserts=[good, bad], deletes=[])

    assert (await reader.list_annotations.execute(student)).items == []


# - - - Listing, editing, deleting - - -


async def test_list_filters_by_item_kind_colour_and_text_and_pages(
    reader: ReaderServices, student: Actor, book: Item, material: Item, clock: FixedClock
) -> None:
    """LIB-8: My library searches and filters the notes, newest first."""
    created: list[UUID] = []
    for item, payload in (
        (book, data(book, quote="mass and force")),
        (book, data(book, kind=AnnotationKind.NOTE, quote=None, note="ask teacher")),
        (material, data(material, color=AnnotationColor.BLUE)),
    ):
        clock.advance(minutes=1)
        created.append((await reader.create_annotation.execute(student, payload)).id)

    everything = await reader.list_annotations.execute(student, limit=2)
    rest = await reader.list_annotations.execute(
        student, limit=2, cursor=everything.next_cursor
    )
    by_item = await reader.list_annotations.execute(
        student, filters=AnnotationFilter(item_id=material.id)
    )
    by_kind = await reader.list_annotations.execute(
        student, filters=AnnotationFilter(kind=AnnotationKind.NOTE)
    )
    by_color = await reader.list_annotations.execute(
        student, filters=AnnotationFilter(color=AnnotationColor.BLUE)
    )
    by_text = await reader.list_annotations.execute(
        student, filters=AnnotationFilter(query="TEACHER")
    )

    assert [a.id for a in everything.items] == [created[2], created[1]]
    assert [a.id for a in rest.items] == [created[0]] and rest.next_cursor is None
    assert [a.id for a in by_item.items] == [created[2]]
    assert [a.id for a in by_kind.items] == [created[1]]
    assert [a.id for a in by_color.items] == [created[2]]
    assert [a.id for a in by_text.items] == [created[1]]


async def test_editing_changes_the_note_and_keeps_the_rest(
    reader: ReaderServices, student: Actor, book: Item, clock: FixedClock
) -> None:
    """LIB-8: PATCH note and colour independently."""
    created = await reader.create_annotation.execute(student, data(book, note="old"))
    clock.advance(minutes=2)

    colour_only = await reader.update_annotation.execute(
        student, created.id, color=AnnotationColor.PINK
    )
    note_cleared = await reader.update_annotation.execute(
        student, created.id, note=None
    )

    assert colour_only.note == "old" and colour_only.color is AnnotationColor.PINK
    assert note_cleared.note is None and note_cleared.color is AnnotationColor.PINK
    assert note_cleared.updated_at == clock.now()


async def test_deleted_annotation_disappears(
    reader: ReaderServices, student: Actor, book: Item
) -> None:
    """LIB-8: deleting twice reports not found the second time."""
    created = await reader.create_annotation.execute(student, data(book))

    await reader.delete_annotation.execute(student, created.id)

    assert (await reader.list_annotations.execute(student)).items == []
    with pytest.raises(AnnotationNotFoundError):
        await reader.delete_annotation.execute(student, created.id)


async def test_notes_stay_listable_after_the_book_is_taken_down(
    reader: ReaderServices, student: Actor, book: Item, uow_factory: UowFactory
) -> None:
    """LIB-14: the user's own notes keep the title; only new notes are refused."""
    created = await reader.create_annotation.execute(student, data(book))
    async with uow_factory() as uow:
        stored = await uow.items.get(book.id)
        assert stored is not None
        stored.status = ItemStatus.UNPUBLISHED
        await uow.items.save(stored)
        await uow.commit()

    page = await reader.list_annotations.execute(student)

    assert [a.id for a in page.items] == [created.id]


# - - - Privacy - - -


async def test_nobody_else_can_read_change_or_delete_a_note(
    reader: ReaderServices,
    student: Actor,
    other_student: Actor,
    teacher: Actor,
    librarian: Actor,
    admin: Actor,
    book: Item,
) -> None:
    """LIB-8, LIB-16: not another student, a teacher, a librarian or Administration."""
    mine = await reader.create_annotation.execute(student, data(book, note="private"))

    for other in (other_student, teacher, librarian, admin):
        assert (await reader.list_annotations.execute(other)).items == []
        assert await reader.export_annotations.execute(other) == ""
        with pytest.raises(AnnotationNotFoundError):
            await reader.update_annotation.execute(other, mine.id, note="hacked")
        with pytest.raises(AnnotationNotFoundError):
            await reader.delete_annotation.execute(other, mine.id)

    still_there = await reader.list_annotations.execute(student)
    assert [a.note for a in still_there.items] == ["private"]


async def test_same_client_id_of_two_users_makes_two_annotations(
    reader: ReaderServices, student: Actor, other_student: Actor, book: Item
) -> None:
    """LIB-16: `client_id` is unique per user, not global."""
    payload = data(book)

    first = await reader.create_annotation.execute(student, payload)
    second = await reader.create_annotation.execute(other_student, payload)

    assert first.id != second.id


# - - - Export - - -


async def test_export_is_markdown_grouped_by_item_with_quote_note_and_page(
    reader: ReaderServices, student: Actor, book: Item, material: Item
) -> None:
    """LIB-8: the export reads well and keeps the page references."""
    await reader.create_annotation.execute(
        student, data(book, locator={"page": 54}, note="Exam topic")
    )
    await reader.create_annotation.execute(
        student,
        data(book, kind=AnnotationKind.BOOKMARK, quote=None, locator={"page": 7}),
    )
    await reader.create_annotation.execute(
        student, data(material, quote="line one\nline two")
    )

    everything = await reader.export_annotations.execute(student)
    one_item = await reader.export_annotations.execute(student, item_id=material.id)

    assert everything.index("# Kinematics notes") < everything.index("# Physics 10")
    physics = everything.split("# Physics 10")[1]
    assert physics.index("p. 7") < physics.index("p. 54")
    assert "- **highlight** (yellow, p. 54)" in physics
    assert "  > A body keeps its state of rest" in physics
    assert "  Exam topic" in physics
    assert "- **bookmark** (yellow, p. 7)" in physics
    assert "  > line one\n  > line two" in one_item
    assert "Physics 10" not in one_item
