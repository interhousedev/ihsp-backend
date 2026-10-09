"""LIB-4: reading lists, their entries and the subject hub summaries in PostgreSQL."""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    Importance,
    ItemStatus,
    ListScope,
    ListStatus,
    Visibility,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.library.taxonomy.helpers import (
    NOW,
    item_entry,
    link_entry,
    make_reading_list,
    make_topic,
)

StoreItem = Callable[[Item], Awaitable[Item]]
SUBJECT = new_id()
OWNER = new_id()


async def test_list_round_trip_and_update(uow_factory: UowFactory) -> None:
    """LIB-4: every field of a list is stored."""
    group = new_id()
    reading_list = make_reading_list(
        OWNER, scope=ListScope.GROUPS, subject_id=SUBJECT, group_ids=[group]
    )
    reading_list.year_of_study = 1
    reading_list.term_half = 2
    async with uow_factory() as uow:
        await uow.lists.add(reading_list)
        reading_list.title = "Literature, year 1"
        reading_list.status = ListStatus.ARCHIVED
        reading_list.updated_at = NOW + timedelta(days=1)
        await uow.lists.save(reading_list)
        loaded = await uow.lists.get(reading_list.id)
        missing = await uow.lists.get(new_id())

    assert missing is None
    assert loaded is not None
    assert loaded.title == "Literature, year 1"
    assert loaded.status is ListStatus.ARCHIVED
    assert (loaded.scope, loaded.group_ids, loaded.subject_id) == (
        ListScope.GROUPS,
        [group],
        SUBJECT,
    )
    assert (loaded.year_of_study, loaded.term_half, loaded.academic_year) == (
        1,
        2,
        "2026-2027",
    )
    assert loaded.updated_at == NOW + timedelta(days=1)


async def test_find_filters_and_orders_by_latest_change(
    uow_factory: UowFactory,
) -> None:
    """LIB-4: subject, owner, group and status filters; newest change first."""
    group = new_id()
    old = make_reading_list(OWNER, title="Old", subject_id=SUBJECT)
    newer = make_reading_list(
        OWNER,
        title="Newer",
        subject_id=SUBJECT,
        updated_at=NOW + timedelta(hours=1),
    )
    draft = make_reading_list(
        new_id(), title="Draft", status=ListStatus.DRAFT, subject_id=SUBJECT
    )
    groups = make_reading_list(
        new_id(), title="Groups", scope=ListScope.GROUPS, group_ids=[group]
    )
    async with uow_factory() as uow:
        for each in (old, newer, draft, groups):
            await uow.lists.add(each)
        in_subject = await uow.lists.find(subject_id=SUBJECT)
        mine = await uow.lists.find(owner_id=OWNER)
        drafts = await uow.lists.find(status=ListStatus.DRAFT)
        of_group = await uow.lists.find(group_id=group)

    assert [x.title for x in in_subject] == ["Newer", "Old", "Draft"]
    assert [x.title for x in mine] == ["Newer", "Old"]
    assert [x.title for x in drafts] == ["Draft"]
    assert [x.title for x in of_group] == ["Groups"]


async def test_entries_round_trip_and_replace_in_one_step(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-4: PUT /items replaces the entries atomically."""
    book = await store_item(make_book())
    reading_list = make_reading_list(OWNER, subject_id=SUBJECT)
    topic = make_topic(SUBJECT)
    async with uow_factory() as uow:
        await uow.lists.add(reading_list)
        await uow.taxonomy.add_topic(topic)
        await uow.lists.replace_entries(
            reading_list.id,
            [
                item_entry(
                    0,
                    book.id,
                    Importance.ESSENTIAL,
                    page_from=10,
                    page_to=20,
                    week_label="Week 2",
                    due_on=date(2026, 11, 2),
                    topic_id=topic.id,
                    note="Chapter 1",
                ),
                link_entry(1),
            ],
        )
        first = (await uow.lists.entries([reading_list.id]))[reading_list.id]
        await uow.lists.replace_entries(
            reading_list.id, [link_entry(0, "https://b.example")]
        )
        second = (await uow.lists.entries([reading_list.id]))[reading_list.id]
        await uow.lists.replace_entries(reading_list.id, [])
        empty = await uow.lists.entries([reading_list.id])

    assert [e.position for e in first] == [0, 1]
    assert first[0].item_id == book.id
    assert (first[0].page_from, first[0].page_to) == (10, 20)
    assert first[0].due_on == date(2026, 11, 2)
    assert first[0].topic_id == topic.id
    assert first[0].importance is Importance.ESSENTIAL
    assert first[1].url == "https://example.org/read"
    assert [e.url for e in second] == ["https://b.example"]
    assert empty == {}


async def test_deleting_a_list_removes_its_entries(uow_factory: UowFactory) -> None:
    """LIB-4: DELETE /reading-lists/{id}."""
    reading_list = make_reading_list(OWNER)
    async with uow_factory() as uow:
        await uow.lists.add(reading_list)
        await uow.lists.replace_entries(reading_list.id, [link_entry(0)])
        await uow.lists.delete(reading_list.id)
        gone = await uow.lists.get(reading_list.id)
        entries = await uow.lists.entries([reading_list.id])

    assert gone is None
    assert entries == {}


async def test_clearing_topics_keeps_the_entries(uow_factory: UowFactory) -> None:
    """LIB-4: a deleted topic leaves entries without a topic, not without a row."""
    reading_list = make_reading_list(OWNER)
    topic = make_topic(SUBJECT)
    async with uow_factory() as uow:
        await uow.lists.add(reading_list)
        await uow.taxonomy.add_topic(topic)
        await uow.lists.replace_entries(
            reading_list.id,
            [item_entry(0, new_id(), topic_id=topic.id), link_entry(1)],
        )
        changed = await uow.lists.clear_topic([topic.id])
        entries = (await uow.lists.entries([reading_list.id]))[reading_list.id]

    assert changed == 1
    assert [e.topic_id for e in entries] == [None, None]


async def test_hub_summaries_show_published_lists_the_group_may_see(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-4: the subject hub lists published subject, school and own group lists."""
    group = new_id()
    visible_book = await store_item(make_book(title="Visible"))
    held_book = await store_item(make_book(title="Held", status=ItemStatus.HELD))
    hidden_book = await store_item(
        make_book(title="Hidden", visibility=Visibility.HIDDEN)
    )
    subject_list = make_reading_list(OWNER, title="Subject", subject_id=SUBJECT)
    school_list = make_reading_list(
        OWNER, title="School", scope=ListScope.SCHOOL, subject_id=SUBJECT
    )
    own_group = make_reading_list(
        OWNER,
        title="Own group",
        scope=ListScope.GROUPS,
        subject_id=SUBJECT,
        group_ids=[group],
    )
    other_group = make_reading_list(
        OWNER,
        title="Other group",
        scope=ListScope.GROUPS,
        subject_id=SUBJECT,
        group_ids=[new_id()],
    )
    draft = make_reading_list(
        OWNER, title="Draft", subject_id=SUBJECT, status=ListStatus.DRAFT
    )
    elsewhere = make_reading_list(OWNER, title="Elsewhere", subject_id=new_id())
    async with uow_factory() as uow:
        for each in (
            subject_list,
            school_list,
            own_group,
            other_group,
            draft,
            elsewhere,
        ):
            await uow.lists.add(each)
        await uow.lists.replace_entries(
            subject_list.id,
            [
                item_entry(0, visible_book.id, Importance.ESSENTIAL),
                item_entry(1, held_book.id, Importance.ESSENTIAL),
                item_entry(2, hidden_book.id),
                link_entry(3, importance=Importance.ESSENTIAL),
                link_entry(4),
            ],
        )
        for_group = await uow.lists.summaries_for_subject(SUBJECT, group_id=group)
        for_nobody = await uow.lists.summaries_for_subject(SUBJECT, group_id=None)

    assert [s.title for s in for_group] == ["Own group", "School", "Subject"]
    assert [s.title for s in for_nobody] == ["School", "Subject"]
    subject = next(s for s in for_group if s.title == "Subject")
    assert (subject.entries, subject.essential_entries) == (3, 2)
    empty = next(s for s in for_group if s.title == "School")
    assert (empty.entries, empty.essential_entries) == (0, 0)
