"""LIB-4, LIB-2: reading lists: audiences, permissions, read status."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.taxonomy.update_reading_list import ListChanges
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
    ShelfState,
)
from app.modules.library.domain.errors import (
    ItemNotFoundError,
    ListNotFoundError,
    ListTooLongError,
)
from app.modules.library.domain.reading_list import EntryDraft
from app.modules.library.domain.taxonomy_errors import ListForbiddenError
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.factories.library import make_book
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.library.taxonomy.conftest import Recorded

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


def entry(item_id: UUID | None = None, **fields: object) -> EntryDraft:
    """An entry draft; an item by default is `essential`."""
    return EntryDraft(
        importance=Importance.ESSENTIAL,
        item_id=item_id,
        **fields,  # type: ignore[arg-type]
    )


async def test_teacher_writes_a_list_for_a_subject_they_teach(
    library: LibraryServices,
    teacher: Actor,
    academic: FakeAcademicDirectory,
    subject_id: UUID,
) -> None:
    """LIB-4: a teacher of the subject creates a draft list of their own."""
    academic.teaches.add((teacher.user_id, subject_id))

    detail = await library.taxonomy.create_reading_list.execute(
        teacher, title="Mechanics", scope=ListScope.SUBJECT, subject_id=subject_id
    )

    assert detail.card.status is ListStatus.DRAFT
    assert detail.card.subject is not None and detail.card.subject.name == "Physics"
    assert detail.card.owner.name == "Dilnoza Rahimova"
    assert detail.can_edit


async def test_teacher_cannot_write_for_a_foreign_subject_or_the_school(
    library: LibraryServices, teacher: Actor, subject_id: UUID
) -> None:
    """LIB-4: other subjects and school lists are for librarians."""
    for scope, subject in ((ListScope.SUBJECT, subject_id), (ListScope.SCHOOL, None)):
        with pytest.raises(ListForbiddenError):
            await library.taxonomy.create_reading_list.execute(
                teacher, title="Nope", scope=scope, subject_id=subject
            )


async def test_librarian_writes_a_school_list(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-2: librarians write for the whole school."""
    detail = await library.taxonomy.create_reading_list.execute(
        librarian, title="Summer", scope=ListScope.SCHOOL, status=ListStatus.PUBLISHED
    )

    assert detail.card.status is ListStatus.PUBLISHED
    assert detail.card.scope is ListScope.SCHOOL


async def test_group_list_needs_groups_the_teacher_teaches_and_notifies_them(
    library: LibraryServices,
    teacher: Actor,
    student: Actor,
    academic: FakeAcademicDirectory,
    subject_id: UUID,
    recorded: Recorded,
) -> None:
    """LIB-4: publishing a list for groups tells the students of the groups once."""
    group, stranger = new_id(), new_id()
    academic.teaches.add((teacher.user_id, subject_id))
    academic.group_names[group] = "2TN2"
    academic.teacher_group_ids[teacher.user_id] = [group]
    academic.members[group] = [student.user_id]
    with pytest.raises(ListForbiddenError):
        await library.taxonomy.create_reading_list.execute(
            teacher,
            title="Foreign",
            scope=ListScope.GROUPS,
            subject_id=subject_id,
            group_ids=[stranger],
        )

    created = await library.taxonomy.create_reading_list.execute(
        teacher,
        title="Mechanics",
        scope=ListScope.GROUPS,
        subject_id=subject_id,
        group_ids=[group],
    )
    assert recorded.notifications == []
    await library.taxonomy.update_reading_list.execute(
        teacher, created.card.id, ListChanges(status=ListStatus.PUBLISHED)
    )
    await library.taxonomy.update_reading_list.execute(
        teacher, created.card.id, ListChanges(title="Mechanics 2")
    )

    assert [n.type for n in recorded.notifications] == [
        NotificationType.LIBRARY_READING_LIST_NEW
    ]
    assert recorded.notifications[0].user_id == student.user_id


async def test_entries_show_cards_and_my_read_status(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    store_item: StoreItem,
    academic: FakeAcademicDirectory,
) -> None:
    """LIB-4: entries carry cards, links, and the viewer's shelf-derived status."""
    book = await store_item(make_book(title="Fizika 10"))
    other = await store_item(make_book(title="Kimyo 10"))
    created = await library.taxonomy.create_reading_list.execute(
        librarian, title="Term 1", scope=ListScope.SCHOOL, status=ListStatus.PUBLISHED
    )
    await library.taxonomy.replace_list_entries.execute(
        librarian,
        created.card.id,
        [
            entry(book.id, page_from=10, page_to=20),
            EntryDraft(importance=Importance.FURTHER, item_id=other.id),
            EntryDraft(
                importance=Importance.RECOMMENDED,
                url="https://example.org/lecture",
                title="Lecture",
            ),
        ],
    )
    await library.reader.put_shelf_entry.execute(
        student, book.id, ShelfState.DONE, locale="en"
    )

    detail = await library.taxonomy.get_reading_list.execute(student, created.card.id)

    assert [e.position for e in detail.entries] == [0, 1, 2]
    assert (
        detail.entries[0].item is not None
        and detail.entries[0].item.title == "Fizika 10"
    )
    assert detail.entries[0].read_state is ShelfState.DONE
    assert detail.entries[1].read_state is None
    assert detail.entries[2].item is None and detail.entries[2].url is not None
    assert (detail.card.essential_count, detail.card.essential_done) == (1, 1)
    assert not detail.can_edit


async def test_entries_must_be_visible_and_within_the_limit(
    library: LibraryServices, librarian: Actor, store_item: StoreItem
) -> None:
    """LIB-4: at most 100 entries; unknown items are refused."""
    created = await library.taxonomy.create_reading_list.execute(
        librarian, title="Big", scope=ListScope.SCHOOL
    )
    book = await store_item(make_book())
    too_many = [entry(book.id) for _ in range(library.core.settings.list_max_items + 1)]

    with pytest.raises(ListTooLongError):
        await library.taxonomy.replace_list_entries.execute(
            librarian, created.card.id, too_many
        )
    with pytest.raises(ItemNotFoundError):
        await library.taxonomy.replace_list_entries.execute(
            librarian, created.card.id, [entry(new_id())]
        )


async def test_students_see_published_lists_of_their_group_only(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    other_student: Actor,
    academic: FakeAcademicDirectory,
) -> None:
    """LIB-4: drafts and the lists of other groups are not found."""
    mine, theirs = new_id(), new_id()
    academic.groups[student.user_id] = mine
    academic.groups[other_student.user_id] = theirs
    academic.members[mine] = [student.user_id]
    academic.group_names[mine] = "2TN2"
    academic.group_names[theirs] = "2TN3"
    own = await library.taxonomy.create_reading_list.execute(
        librarian,
        title="For 2TN2",
        scope=ListScope.GROUPS,
        group_ids=[mine],
        status=ListStatus.PUBLISHED,
    )
    draft = await library.taxonomy.create_reading_list.execute(
        librarian, title="Draft", scope=ListScope.SCHOOL
    )

    listed = await library.taxonomy.list_reading_lists.execute(student)
    other_listed = await library.taxonomy.list_reading_lists.execute(other_student)

    assert [c.title for c in listed] == ["For 2TN2"]
    assert other_listed == []
    with pytest.raises(ListNotFoundError):
        await library.taxonomy.get_reading_list.execute(student, draft.card.id)
    assert (await library.taxonomy.get_reading_list.execute(student, own.card.id)).card


async def test_only_the_owner_or_a_librarian_deletes_a_list(
    library: LibraryServices,
    teacher: Actor,
    librarian: Actor,
    academic: FakeAcademicDirectory,
    subject_id: UUID,
) -> None:
    """LIB-2: another teacher sees a published list but cannot delete it."""
    academic.teaches.add((teacher.user_id, subject_id))
    created = await library.taxonomy.create_reading_list.execute(
        teacher,
        title="Mechanics",
        scope=ListScope.SUBJECT,
        subject_id=subject_id,
        status=ListStatus.PUBLISHED,
    )

    await library.taxonomy.delete_reading_list.execute(librarian, created.card.id)

    with pytest.raises(ListNotFoundError):
        await library.taxonomy.get_reading_list.execute(teacher, created.card.id)
