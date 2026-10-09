"""LIB-11: SQL book plans and lesson links."""

import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.book_plan import BookPlan, PlanSection
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, Visibility
from app.modules.library.ports.plan_repository import LessonItemRef
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import make_book

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
StoreItem = Callable[[Item], Awaitable[Item]]


def plan(
    subject_id: UUID, item_id: UUID, *, year: int = 1, minutes: int = 0, count: int = 2
) -> BookPlan:
    """A plan of `count` sections saved `minutes` after NOW."""
    return BookPlan(
        id=new_id(),
        subject_id=subject_id,
        year_of_study=year,
        item_id=item_id,
        sections=tuple(
            PlanSection(
                n=i, title=f"Section {i}", page_from=i * 10, page_to=i * 10 + 9, hours=2
            )
            for i in range(1, count + 1)
        ),
        updated_at=NOW + dt.timedelta(minutes=minutes),
    )


def link(lesson_id: UUID, item_id: UUID, label: str, teacher: UUID) -> LessonItemRef:
    """A link to pages 54 to 61."""
    return LessonItemRef(
        lesson_id=lesson_id,
        item_id=item_id,
        section_label=label,
        page_from=54,
        page_to=61,
        set_by=teacher,
        updated_at=NOW,
    )


async def test_plan_round_trips_with_its_sections(uow_factory: UowFactory) -> None:
    """LIB-11: sections come back in order with their pages and hours."""
    subject, item = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.save_plan(plan(subject, item, count=3))

        loaded = await uow.plans.get_plan(subject, 1)
        other_year = await uow.plans.get_plan(subject, 2)

    assert other_year is None
    assert loaded is not None
    assert [s.title for s in loaded.sections] == ["Section 1", "Section 2", "Section 3"]
    assert loaded.sections[1] == PlanSection(2, "Section 2", 20, 29, 2.0)
    assert loaded.item_id == item
    assert loaded.updated_at == NOW


async def test_saving_again_replaces_the_sections_of_the_same_book(
    uow_factory: UowFactory,
) -> None:
    """LIB-11: a teacher edits the plan, the row is updated."""
    subject, item = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.save_plan(plan(subject, item, count=3))
        await uow.plans.save_plan(plan(subject, item, count=1, minutes=5))

        loaded = await uow.plans.get_plan(subject, 1)

    assert loaded is not None
    assert len(loaded.sections) == 1
    assert loaded.updated_at == NOW + dt.timedelta(minutes=5)


async def test_choosing_another_textbook_drops_the_old_plan(
    uow_factory: UowFactory,
) -> None:
    """LIB-11: one textbook per subject and year of study."""
    subject, old_book, new_book = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.save_plan(plan(subject, old_book))
        await uow.plans.save_plan(plan(subject, new_book, minutes=3))
        await uow.plans.save_plan(plan(subject, old_book, year=2))

        year_one = await uow.plans.get_plan(subject, 1)
        year_two = await uow.plans.get_plan(subject, 2)

    assert year_one is not None and year_one.item_id == new_book
    assert year_two is not None and year_two.item_id == old_book


async def test_lesson_links_keep_the_order_and_are_replaced_as_a_set(
    uow_factory: UowFactory,
) -> None:
    """LIB-11: the teacher's order is the display order; a second set replaces it."""
    lesson, teacher, item = new_id(), new_id(), new_id()
    labels = ["Z first", "A second", "M third"]
    async with uow_factory() as uow:
        await uow.plans.set_lesson_refs(
            lesson, [link(lesson, item, label, teacher) for label in labels]
        )
        stored = await uow.plans.list_lesson_refs(lesson)
        await uow.plans.set_lesson_refs(lesson, [link(lesson, item, "Only", teacher)])
        replaced = await uow.plans.list_lesson_refs(lesson)

    assert [r.section_label for r in stored] == labels
    assert stored[0].set_by == teacher and stored[0].page_to == 61
    assert [r.section_label for r in replaced] == ["Only"]


async def test_clearing_the_links_removes_them(uow_factory: UowFactory) -> None:
    """LIB-11: an empty set removes every link of the lesson."""
    lesson, teacher, item = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.set_lesson_refs(lesson, [link(lesson, item, "x", teacher)])
        await uow.plans.set_lesson_refs(lesson, [])

        assert await uow.plans.list_lesson_refs(lesson) == []


async def test_lesson_refs_carry_titles_and_skip_unlisted_items(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-11: a taken-down or hidden book is not shown next to the lesson."""
    shown = await store_item(make_book(title="Physics 10"))
    taken_down = await store_item(
        make_book(title="Removed book", status=ItemStatus.UNPUBLISHED)
    )
    hidden = await store_item(make_book(title="Hidden", visibility=Visibility.HIDDEN))
    lesson, bare, teacher = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.set_lesson_refs(
            lesson,
            [
                link(lesson, shown.id, "Section 12", teacher),
                link(lesson, taken_down.id, "Section 13", teacher),
                link(lesson, hidden.id, "Section 14", teacher),
            ],
        )

        views = await uow.plans.lesson_refs([lesson, bare])

    assert list(views) == [lesson]
    assert [(v.item_id, v.title, v.section_label) for v in views[lesson]] == [
        (shown.id, "Physics 10", "Section 12")
    ]
    assert views[lesson][0].page_from == 54


async def test_linked_lessons_groups_stored_links_by_lesson(
    uow_factory: UowFactory,
) -> None:
    """LIB-11: the suggestion reads the links of earlier lessons."""
    first, second, empty, teacher, item = new_id(), new_id(), new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.plans.set_lesson_refs(first, [link(first, item, "A", teacher)])
        await uow.plans.set_lesson_refs(second, [link(second, item, "B", teacher)])

        grouped = await uow.plans.linked_lessons([first, second, empty])

    assert set(grouped) == {first, second}
    assert grouped[second][0].section_label == "B"
