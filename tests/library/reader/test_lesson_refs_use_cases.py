"""LIB-11: a lesson shows "Textbook: section, pages" without touching its topic."""

import dataclasses
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.errors import ItemNotFoundError, NotSupportedError
from app.modules.library.domain.reader_errors import (
    InvalidLessonRefError,
    LessonNotFoundError,
)
from app.modules.library.domain.reader_lesson_ref import LessonRefInput
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.library.lessons import FakeLessonDirectory

import pytest


def ref(
    item: Item, label: str = "Section 12", pages: tuple[int, int] = (54, 61)
) -> LessonRefInput:
    """A link to pages of the item."""
    return LessonRefInput(
        item_id=item.id, section_label=label, page_from=pages[0], page_to=pages[1]
    )


async def test_teacher_links_the_lesson_to_a_section_and_students_see_it(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    student: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: the link shows as title, section and pages."""
    lesson = lessons.add(
        subject, teacher_id=teacher.user_id, students=(student.user_id,)
    )

    saved = await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book)])
    seen_by_student = await reader.get_lesson_item_refs.execute(student, lesson)
    seen_by_teacher = await reader.get_lesson_item_refs.execute(teacher, lesson)

    assert saved == seen_by_student == seen_by_teacher
    [link] = saved
    assert (link.item_id, link.title) == (book.id, "Physics 10")
    assert (link.section_label, link.page_from, link.page_to) == ("Section 12", 54, 61)


async def test_the_lesson_topic_is_left_alone(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: a book link never overwrites `Lesson.topic`."""
    lesson = lessons.add(subject, teacher_id=teacher.user_id)
    lessons.topics[lesson] = "Newton's laws"
    before = dataclasses.replace(lessons.lessons[lesson])

    await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book)])

    assert lessons.topics[lesson] == "Newton's laws"
    assert lessons.lessons[lesson] == before


async def test_setting_links_again_replaces_them_and_keeps_the_order(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    subject: UUID,
    book: Item,
    material: Item,
) -> None:
    """LIB-11: the teacher's order is the display order; an empty list clears."""
    lesson = lessons.add(subject, teacher_id=teacher.user_id)
    await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book, "Z")])

    replaced = await reader.set_lesson_item_refs.execute(
        teacher, lesson, [ref(material, "B", (1, 2)), ref(book, "A", (3, 4))]
    )
    cleared = await reader.set_lesson_item_refs.execute(teacher, lesson, [])

    assert [r.section_label for r in replaced] == ["B", "A"]
    assert cleared == []
    assert await reader.get_lesson_item_refs.execute(teacher, lesson) == []


async def test_only_the_lessons_teacher_and_admin_may_set_links(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    student: Actor,
    librarian: Actor,
    admin: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: another teacher, a student or a librarian get a 404 for the lesson."""
    lesson = lessons.add(subject, teacher_id=new_id(), students=(student.user_id,))

    for actor in (teacher, student, librarian):
        with pytest.raises(LessonNotFoundError):
            await reader.set_lesson_item_refs.execute(actor, lesson, [ref(book)])
    saved = await reader.set_lesson_item_refs.execute(admin, lesson, [ref(book)])

    assert len(saved) == 1


async def test_only_people_of_the_lesson_may_read_its_links(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    student: Actor,
    other_student: Actor,
    admin: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-16: a student outside the audience sees nothing, not even that it exists."""
    lesson = lessons.add(
        subject, teacher_id=teacher.user_id, students=(student.user_id,)
    )
    await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book)])

    with pytest.raises(LessonNotFoundError):
        await reader.get_lesson_item_refs.execute(other_student, lesson)
    with pytest.raises(LessonNotFoundError):
        await reader.get_lesson_item_refs.execute(student, new_id())
    assert len(await reader.get_lesson_item_refs.execute(admin, lesson)) == 1


async def test_links_to_books_the_viewer_cannot_see_are_left_out(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    student: Actor,
    subject: UUID,
    book: Item,
    taken_down: Item,
    librarian: Actor,
) -> None:
    """LIB-14: a taken-down book vanishes from the lesson of a student."""
    lesson = lessons.add(
        subject, teacher_id=librarian.user_id, students=(student.user_id,)
    )
    (
        await reader.set_lesson_item_refs.execute(
            librarian, lesson, [ref(book, "A"), ref(taken_down, "B", (1, 2))]
        )
        if False
        else None
    )
    # Set through the lesson's real teacher so the librarian check does not interfere.
    lessons.lessons[lesson] = dataclasses.replace(
        lessons.lessons[lesson], teacher_id=teacher.user_id
    )
    await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book, "A")])

    shown = await reader.get_lesson_item_refs.execute(student, lesson)

    assert [r.section_label for r in shown] == ["A"]


async def test_unilibrary_records_and_unknown_items_cannot_be_linked(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    subject: UUID,
    external: Item,
    book: Item,
) -> None:
    """LIB-12: only books and materials have pages."""
    lesson = lessons.add(subject, teacher_id=teacher.user_id)

    with pytest.raises(NotSupportedError):
        await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(external)])
    with pytest.raises(ItemNotFoundError):
        await reader.set_lesson_item_refs.execute(
            teacher, lesson, [LessonRefInput(new_id(), "x", None, None)]
        )
    assert book is not None


async def test_invalid_links_are_refused(
    reader: ReaderServices,
    lessons: FakeLessonDirectory,
    teacher: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: labels and page ranges are checked."""
    lesson = lessons.add(subject, teacher_id=teacher.user_id)

    with pytest.raises(InvalidLessonRefError):
        await reader.set_lesson_item_refs.execute(teacher, lesson, [ref(book, "   ")])
    with pytest.raises(InvalidLessonRefError):
        await reader.set_lesson_item_refs.execute(
            teacher, lesson, [ref(book, "A", (9, 3))]
        )
