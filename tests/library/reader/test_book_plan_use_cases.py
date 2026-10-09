"""LIB-11: teachers and librarians keep a textbook plan per subject and year."""

from uuid import UUID

from app.modules.library.domain.book_plan import PlanSection
from app.modules.library.domain.entities import Item
from app.modules.library.domain.errors import ItemNotFoundError, NotSupportedError
from app.modules.library.domain.reader_errors import (
    InvalidBookPlanError,
    SubjectNotFoundError,
)
from app.modules.library.wiring_reader import ReaderServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.fakes.library.academic import FakeAcademicDirectory

import pytest


def sections(count: int = 3) -> list[PlanSection]:
    """Ten pages per section, two hours each."""
    return [
        PlanSection(
            n=i, title=f"Section {i}", page_from=i * 10, page_to=i * 10 + 9, hours=2
        )
        for i in range(1, count + 1)
    ]


async def test_teacher_of_the_subject_saves_and_reads_the_plan(
    reader: ReaderServices,
    academic: FakeAcademicDirectory,
    teacher: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: the plan comes back with the title of the book."""
    academic.teaches.add((teacher.user_id, subject))

    saved = await reader.put_book_plan.execute(
        teacher,
        subject_id=subject,
        year_of_study=1,
        item_id=book.id,
        sections=sections(),
    )
    loaded = await reader.get_book_plan.execute(
        teacher, subject_id=subject, year_of_study=1
    )

    assert loaded == saved
    assert loaded is not None
    assert loaded.item_title == "Physics 10"
    assert [s.title for s in loaded.sections] == ["Section 1", "Section 2", "Section 3"]


async def test_plan_of_another_year_or_subject_is_empty(
    reader: ReaderServices,
    academic: FakeAcademicDirectory,
    teacher: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: no plan is `None`, not an error."""
    academic.teaches.add((teacher.user_id, subject))
    await reader.put_book_plan.execute(
        teacher,
        subject_id=subject,
        year_of_study=1,
        item_id=book.id,
        sections=sections(),
    )

    assert (
        await reader.get_book_plan.execute(teacher, subject_id=subject, year_of_study=2)
        is None
    )
    assert (
        await reader.get_book_plan.execute(
            teacher, subject_id=new_id(), year_of_study=1
        )
        is None
    )


async def test_librarian_and_admin_may_plan_any_subject(
    reader: ReaderServices,
    librarian: Actor,
    admin: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-2: staff of the library do not need to teach the subject."""
    for actor, year in ((librarian, 1), (admin, 2)):
        saved = await reader.put_book_plan.execute(
            actor,
            subject_id=subject,
            year_of_study=year,
            item_id=book.id,
            sections=sections(1),
        )
        assert saved.year_of_study == year


async def test_teacher_of_another_subject_and_students_are_refused(
    reader: ReaderServices,
    teacher: Actor,
    student: Actor,
    subject: UUID,
    book: Item,
) -> None:
    """LIB-11: only the subject's teachers and librarians write plans."""
    for actor in (teacher, student):
        with pytest.raises(ForbiddenError):
            await reader.put_book_plan.execute(
                actor,
                subject_id=subject,
                year_of_study=1,
                item_id=book.id,
                sections=sections(),
            )
    with pytest.raises(ForbiddenError):
        await reader.get_book_plan.execute(student, subject_id=subject, year_of_study=1)


async def test_unknown_subject_is_not_found(
    reader: ReaderServices, librarian: Actor, book: Item
) -> None:
    """LIB-11: a plan needs a real subject."""
    with pytest.raises(SubjectNotFoundError):
        await reader.put_book_plan.execute(
            librarian,
            subject_id=new_id(),
            year_of_study=1,
            item_id=book.id,
            sections=sections(),
        )


async def test_plan_needs_a_visible_book_or_material_with_files(
    reader: ReaderServices,
    librarian: Actor,
    subject: UUID,
    external: Item,
    material: Item,
) -> None:
    """LIB-12: UniLibrary records have no pages to plan."""
    with pytest.raises(NotSupportedError):
        await reader.put_book_plan.execute(
            librarian,
            subject_id=subject,
            year_of_study=1,
            item_id=external.id,
            sections=sections(),
        )
    with pytest.raises(ItemNotFoundError):
        await reader.put_book_plan.execute(
            librarian,
            subject_id=subject,
            year_of_study=1,
            item_id=new_id(),
            sections=sections(),
        )
    saved = await reader.put_book_plan.execute(
        librarian,
        subject_id=subject,
        year_of_study=1,
        item_id=material.id,
        sections=sections(1),
    )
    assert saved.item_id == material.id


async def test_sections_are_checked_against_the_length_of_the_book(
    reader: ReaderServices, librarian: Actor, subject: UUID, book: Item
) -> None:
    """LIB-11: the factory book has 120 pages."""
    with pytest.raises(InvalidBookPlanError):
        await reader.put_book_plan.execute(
            librarian,
            subject_id=subject,
            year_of_study=1,
            item_id=book.id,
            sections=[
                PlanSection(n=1, title="Too far", page_from=100, page_to=121, hours=1)
            ],
        )


async def test_choosing_another_textbook_replaces_the_plan(
    reader: ReaderServices, librarian: Actor, subject: UUID, book: Item, material: Item
) -> None:
    """LIB-11: one textbook per subject and year."""
    await reader.put_book_plan.execute(
        librarian,
        subject_id=subject,
        year_of_study=1,
        item_id=book.id,
        sections=sections(),
    )
    await reader.put_book_plan.execute(
        librarian,
        subject_id=subject,
        year_of_study=1,
        item_id=material.id,
        sections=sections(1),
    )

    loaded = await reader.get_book_plan.execute(
        librarian, subject_id=subject, year_of_study=1
    )

    assert loaded is not None and loaded.item_id == material.id


async def test_plan_of_a_taken_down_book_is_hidden(
    reader: ReaderServices,
    librarian: Actor,
    teacher: Actor,
    subject: UUID,
    taken_down: Item,
) -> None:
    """LIB-14: a plan never shows a book the caller may not see."""
    # A librarian sees reviewable items, a teacher does not see unpublished ones.
    await reader.put_book_plan.execute(
        librarian,
        subject_id=subject,
        year_of_study=1,
        item_id=taken_down.id,
        sections=sections(),
    )

    assert (
        await reader.get_book_plan.execute(teacher, subject_id=subject, year_of_study=1)
        is None
    )
    assert (
        await reader.get_book_plan.execute(
            librarian, subject_id=subject, year_of_study=1
        )
        is not None
    )
