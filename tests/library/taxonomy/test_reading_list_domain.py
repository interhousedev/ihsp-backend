"""LIB-4: reading list rules: audience, entries, read status, who sees and edits."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.library.domain.enums import (
    Importance,
    ListScope,
    ListStatus,
    ShelfState,
)
from app.modules.library.domain.errors import ListTooLongError
from app.modules.library.domain.reading_list import (
    EntryDraft,
    ReadingList,
    build_entries,
    clean_list_text,
    essential_progress,
    validate_audience,
)
from app.modules.library.domain.reading_list_policy import (
    can_edit_list,
    can_view_list,
    needs_staff,
)
from app.modules.library.domain.taxonomy_errors import (
    ListEntryInvalidError,
    ListInvalidError,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
SUBJECT = new_id()
GROUP = new_id()


def make_list(
    *,
    owner: UUID | None = None,
    scope: ListScope = ListScope.SUBJECT,
    status: ListStatus = ListStatus.PUBLISHED,
    group_ids: list[UUID] | None = None,
) -> ReadingList:
    return ReadingList(
        id=new_id(),
        owner_id=owner or new_id(),
        title="Required reading",
        scope=scope,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        subject_id=SUBJECT,
        group_ids=group_ids or [],
    )


def link(**fields: object) -> EntryDraft:
    base = EntryDraft(
        importance=Importance.RECOMMENDED, url="https://example.org/article"
    )
    return replace(base, **fields)


# - - - Audience - - -


def test_subject_list_needs_a_subject_and_no_groups() -> None:
    """LIB-4: a subject list is for one subject, not for groups."""
    assert validate_audience(ListScope.SUBJECT, SUBJECT, []) == []
    with pytest.raises(ListInvalidError):
        validate_audience(ListScope.SUBJECT, None, [])
    with pytest.raises(ListInvalidError):
        validate_audience(ListScope.SUBJECT, SUBJECT, [GROUP])


def test_group_list_needs_groups_and_drops_repeated_ones() -> None:
    """LIB-4: specific groups, each listed once."""
    assert validate_audience(ListScope.GROUPS, SUBJECT, [GROUP, GROUP]) == [GROUP]
    with pytest.raises(ListInvalidError):
        validate_audience(ListScope.GROUPS, SUBJECT, [])


def test_school_list_has_no_groups() -> None:
    """LIB-4: a school-wide list does not name groups."""
    assert validate_audience(ListScope.SCHOOL, None, []) == []
    with pytest.raises(ListInvalidError):
        validate_audience(ListScope.SCHOOL, None, [GROUP])


def test_text_fields_are_trimmed_and_blank_titles_refused() -> None:
    """LIB-4: titles are required, descriptions may be empty."""
    assert clean_list_text("  Required   reading ", " ") == ("Required reading", None)
    with pytest.raises(ListInvalidError):
        clean_list_text("  ", None)


# - - - Entries - - -


def test_entries_are_numbered_in_the_order_given() -> None:
    """LIB-4: positions follow the request."""
    drafts = [link(url="https://a.example"), link(url="https://b.example")]

    entries = build_entries(drafts, max_items=100)

    assert [e.position for e in entries] == [0, 1]
    assert [e.url for e in entries] == ["https://a.example", "https://b.example"]


def test_a_list_holds_at_most_the_configured_number_of_entries() -> None:
    """LIB-4: library/list-too-long for the 101st entry."""
    drafts = [link() for _ in range(3)]

    build_entries(drafts, max_items=3)
    with pytest.raises(ListTooLongError) as raised:
        build_entries(drafts, max_items=2)

    assert raised.value.params == {"max": 2}


def test_entry_is_either_an_item_or_a_link() -> None:
    """LIB-4: both or neither of item_id and url is invalid."""
    item_id = new_id()

    assert build_entries([link(url=None, item_id=item_id)], 100)[0].item_id == item_id
    with pytest.raises(ListEntryInvalidError):
        build_entries([link(url=None, item_id=None)], 100)
    with pytest.raises(ListEntryInvalidError):
        build_entries([link(item_id=item_id)], 100)


def test_link_needs_a_web_address_and_gets_a_title() -> None:
    """LIB-4: plain links are http(s) and are shown with a title."""
    entry = build_entries([link(url="https://example.org/a", title=None)], 100)[0]
    named = build_entries([link(title=" Reading ")], 100)[0]

    assert entry.title == "https://example.org/a"
    assert named.title == "Reading"
    for bad in ("javascript:alert(1)", "ftp://example.org", "not a url"):
        with pytest.raises(ListEntryInvalidError):
            build_entries([link(url=bad)], 100)


def test_item_entry_keeps_no_url_or_title() -> None:
    """LIB-4: the card of the item supplies the title."""
    entry = build_entries([link(url=None, item_id=new_id(), title="ignored")], 100)[0]

    assert entry.url is None
    assert entry.title is None


def test_page_range_must_be_positive_and_ordered() -> None:
    """LIB-4: pages start at 1, the end is not before the start."""
    ok = build_entries([link(page_from=5, page_to=9)], 100)[0]
    assert (ok.page_from, ok.page_to) == (5, 9)
    for bad in (
        {"page_from": 0},
        {"page_from": 9, "page_to": 5},
        {"page_to": 5},
    ):
        with pytest.raises(ListEntryInvalidError):
            build_entries([link(**bad)], 100)


def test_note_week_label_and_due_date_are_kept() -> None:
    """LIB-4: the optional fields of an entry round trip; blank ones become None."""
    entry = build_entries(
        [link(note=" Read slowly ", week_label=" Week 3 ", due_on=date(2026, 11, 2))],
        100,
    )[0]
    blank = build_entries([link(note="  ", week_label="")], 100)[0]

    assert (entry.note, entry.week_label, entry.due_on) == (
        "Read slowly",
        "Week 3",
        date(2026, 11, 2),
    )
    assert (blank.note, blank.week_label) == (None, None)


def test_note_over_500_characters_is_refused() -> None:
    """LIB-4: notes are short."""
    with pytest.raises(ListEntryInvalidError):
        build_entries([link(note="x" * 501)], 100)


# - - - Progress - - -


def test_progress_counts_only_essential_entries_that_are_read() -> None:
    """LIB-4: the header shows how many essential entries the student finished."""
    done, reading, nothing = new_id(), new_id(), new_id()
    entries = build_entries(
        [
            link(url=None, item_id=done, importance=Importance.ESSENTIAL),
            link(url=None, item_id=reading, importance=Importance.ESSENTIAL),
            link(url=None, item_id=nothing, importance=Importance.ESSENTIAL),
            link(importance=Importance.ESSENTIAL),
            link(url=None, item_id=new_id(), importance=Importance.FURTHER),
        ],
        100,
    )
    states = {done: ShelfState.DONE, reading: ShelfState.READING}

    assert essential_progress(entries, states) == (4, 1)


# - - - Who sees and edits - - -


@pytest.fixture
def owner(make_actor: Callable[..., Actor]) -> Actor:
    return make_actor(Role.TEACHER)


def test_owner_and_librarians_see_drafts_nobody_else_does(
    owner: Actor, make_actor: Callable[..., Actor]
) -> None:
    """LIB-4: draft and archived lists are for the owner and librarians only."""
    draft = make_list(owner=owner.user_id, status=ListStatus.DRAFT)

    assert can_view_list(draft, owner, group_id=None)
    assert can_view_list(draft, make_actor(Role.LIBRARIAN), group_id=None)
    assert can_view_list(draft, make_actor(Role.ADMIN), group_id=None)
    assert not can_view_list(draft, make_actor(Role.TEACHER), group_id=None)
    assert not can_view_list(draft, make_actor(Role.STUDENT), group_id=GROUP)
    assert not can_view_list(draft, None, group_id=None)


def test_students_see_published_school_subject_and_own_group_lists(
    make_actor: Callable[..., Actor],
) -> None:
    """LIB-4: a group list is visible only to the students of those groups."""
    student = make_actor(Role.STUDENT)
    subject_list = make_list(scope=ListScope.SUBJECT)
    school_list = make_list(scope=ListScope.SCHOOL)
    group_list = make_list(scope=ListScope.GROUPS, group_ids=[GROUP])

    assert can_view_list(subject_list, student, group_id=None)
    assert can_view_list(school_list, student, group_id=None)
    assert can_view_list(group_list, student, group_id=GROUP)
    assert not can_view_list(group_list, student, group_id=new_id())
    assert not can_view_list(group_list, student, group_id=None)


def test_teachers_see_every_published_list(make_actor: Callable[..., Actor]) -> None:
    """LIB-4: staff may look at group lists of colleagues."""
    teacher = make_actor(Role.TEACHER)

    assert can_view_list(
        make_list(scope=ListScope.GROUPS, group_ids=[GROUP]), teacher, group_id=None
    )


def test_only_the_owner_teacher_and_librarians_edit(
    owner: Actor, make_actor: Callable[..., Actor]
) -> None:
    """LIB-4: a teacher edits only their own lists."""
    mine = make_list(owner=owner.user_id)

    assert can_edit_list(mine, owner)
    assert can_edit_list(mine, make_actor(Role.LIBRARIAN))
    assert can_edit_list(mine, make_actor(Role.ADMIN))
    assert not can_edit_list(mine, make_actor(Role.TEACHER))
    assert not can_edit_list(mine, make_actor(Role.STUDENT))


def test_school_lists_and_lists_without_subject_are_staff_work() -> None:
    """LIB-4: teachers write only subject or group lists with a subject."""
    assert needs_staff(ListScope.SCHOOL, SUBJECT)
    assert needs_staff(ListScope.SUBJECT, None)
    assert needs_staff(ListScope.GROUPS, None)
    assert not needs_staff(ListScope.SUBJECT, SUBJECT)
    assert not needs_staff(ListScope.GROUPS, SUBJECT)
