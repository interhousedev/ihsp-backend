"""LIB-13, LIB-14: the librarian queue and its five tabs."""

import dataclasses
import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.materials.views import QueueRowView, QueueTab
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemKind,
    ItemStatus,
    ReportReason,
    Rights,
    UploaderRole,
)
from app.modules.library.domain.moderation_entities import BookSuggestion, Report
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.clock import FixedClock

import pytest

MakePending = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]
StoreItem = Callable[[Item], Awaitable[Item]]


async def queue(
    library: LibraryServices,
    actor: Actor,
    tab: QueueTab,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[QueueRowView], str | None]:
    """One page of a tab."""
    page = await library.materials.list_queue.execute(
        actor, tab, cursor=cursor, limit=limit, locale="en"
    )
    return page.items, page.next_cursor


async def file_report(
    uow_factory: UowFactory,
    item_id: UUID,
    reason: ReportReason,
    at: dt.datetime,
    role: UploaderRole = UploaderRole.STUDENT,
) -> Report:
    """Store an open report."""
    report = Report(
        id=new_id(),
        item_id=item_id,
        reporter_id=new_id(),
        reporter_role=role,
        reason=reason,
        created_at=at,
    )
    async with uow_factory() as uow:
        await uow.moderation.add_report(report)
        await uow.commit()
    return report


async def test_review_tab_lists_pending_materials_oldest_first_with_the_uploader(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    clock: FixedClock,
) -> None:
    """LIB-13: queue rows carry the item card, uploader name, cohort and role."""
    first = await make_pending(student)
    clock.advance(minutes=30)
    second = await make_pending(other_student, title="Optics notes")

    rows, cursor = await queue(library, other_librarian, QueueTab.REVIEW)

    assert [r.item.id for r in rows] == [first, second]
    assert cursor is None
    head = rows[0]
    assert head.kind == "student_material"
    assert head.uploader is not None
    assert (head.uploader.name, head.uploader.cohort, head.uploader.role) == (
        "Aziza K.",
        "2025",
        "student",
    )
    assert head.reports == ()
    assert head.report_ids is None
    assert head.suggestion is None
    assert head.submitted_at == rows[0].submitted_at < rows[1].submitted_at
    assert head.item.title == "Kinematics cheat sheet"


async def test_scan_findings_come_from_the_material_scan(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: what the scan job found is shown to the librarian."""
    item_id = await make_pending(student)
    async with uow_factory() as uow:
        item = await uow.items.get(item_id)
        assert item is not None and item.material is not None
        item.material.scan = {"findings": ["phone_number", "exam_marker"], "x": 1}
        await uow.items.save(item)
        await uow.commit()

    rows, _ = await queue(library, other_librarian, QueueTab.REVIEW)

    assert rows[0].findings == ("phone_number", "exam_marker")


async def test_teacher_materials_in_the_queue_have_their_own_kind(
    build_library: Callable[..., LibraryServices],
    teacher: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
) -> None:
    """LIB-13: with LIBRARY__TEACHER_REVIEW the queue shows teacher uploads too."""
    strict = build_library(teacher_review=True)
    await make_pending(teacher, services=strict)

    rows, _ = await queue(strict, other_librarian, QueueTab.REVIEW)

    assert [r.kind for r in rows] == ["teacher_material"]


async def test_reports_tab_groups_reasons_and_lists_report_ids(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: reasons with counts, the ids to resolve, never the reporters."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    spam = await file_report(uow_factory, item_id, ReportReason.SPAM, clock.now())
    late = clock.now() + dt.timedelta(hours=2)
    copy_a = await file_report(uow_factory, item_id, ReportReason.COPYRIGHT, late)
    copy_b = await file_report(uow_factory, item_id, ReportReason.COPYRIGHT, late)

    rows, _ = await queue(library, other_librarian, QueueTab.REPORTS)

    (row,) = rows
    assert row.kind == "report"
    assert [(r.reason, r.count) for r in row.reports] == [
        (ReportReason.COPYRIGHT, 2),
        (ReportReason.SPAM, 1),
    ]
    assert set(row.report_ids or ()) == {spam.id, copy_a.id, copy_b.id}
    assert row.submitted_at == clock.now()
    assert str(copy_a.reporter_id) not in repr(row)


async def test_held_tab_lists_held_items_and_not_the_reported_ones(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: Reports and Held are different tabs."""
    held = await make_pending(student, title="Held one")
    reported = await make_pending(student, title="Reported one")
    await set_status(held, ItemStatus.HELD, status_reason="reported")
    await set_status(reported, ItemStatus.PUBLISHED)
    await file_report(uow_factory, held, ReportReason.COPYRIGHT, clock.now())
    await file_report(uow_factory, reported, ReportReason.SPAM, clock.now())

    held_rows, _ = await queue(library, other_librarian, QueueTab.HELD)
    report_rows, _ = await queue(library, other_librarian, QueueTab.REPORTS)

    assert [r.item.id for r in held_rows] == [held]
    assert [r.item.id for r in report_rows] == [reported]
    assert held_rows[0].kind == "report"
    assert held_rows[0].report_ids is not None


async def test_rights_tab_lists_unchecked_books_and_expiring_permissions(
    library: LibraryServices,
    other_librarian: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-3: books with an unchecked basis or a permission ending within 60 days."""
    unchecked = make_book(title="Unchecked")
    assert unchecked.book is not None
    unchecked.book.rights_checked_at = None
    expiring = make_book(title="Expiring", rights=Rights.PERMISSION)
    assert expiring.book is not None
    expiring.book.rights_basis = {"permission_expires_on": "2026-11-15"}
    distant = make_book(title="Distant", rights=Rights.PERMISSION)
    assert distant.book is not None
    distant.book.rights_basis = {"permission_expires_on": "2027-11-15"}
    for item in (unchecked, expiring, distant, make_book(title="Settled")):
        await store_item(item)

    rows, _ = await queue(library, other_librarian, QueueTab.RIGHTS)

    assert {r.item.title for r in rows} == {"Unchecked", "Expiring"}
    assert {r.kind for r in rows} == {"rights"}
    assert all(r.item.kind is ItemKind.BOOK for r in rows)
    assert all(r.uploader is None for r in rows)


async def test_suggestions_tab_shows_new_suggestions_with_the_suggester(
    library: LibraryServices,
    student: Actor,
    teacher: Actor,
    other_librarian: Actor,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-2: a suggestion row has a card without id and the suggester's label."""
    mine = BookSuggestion(
        id=new_id(),
        user_id=student.user_id,
        title="Atom physics workbook",
        created_at=clock.now(),
        url="https://example.org/atom",
        note="Good for the olympiad group",
    )
    theirs = dataclasses.replace(
        mine,
        id=new_id(),
        user_id=teacher.user_id,
        title="Optics",
        created_at=clock.now() + dt.timedelta(hours=1),
        url=None,
        note=None,
    )
    async with uow_factory() as uow:
        await uow.moderation.add_suggestion(theirs)
        await uow.moderation.add_suggestion(mine)
        await uow.commit()

    rows, _ = await queue(library, other_librarian, QueueTab.SUGGESTIONS)

    assert [r.kind for r in rows] == ["suggestion", "suggestion"]
    first = rows[0]
    assert first.item.id is None and first.item.slug is None
    assert first.item.title == "Atom physics workbook"
    assert first.item.tag_source == "book"
    assert first.suggestion is not None
    assert first.suggestion.id == mine.id
    assert first.suggestion.user_name == "Aziza K., 2025"
    assert first.suggestion.url == "https://example.org/atom"
    assert first.suggestion.note == "Good for the olympiad group"
    assert rows[1].suggestion is not None
    assert rows[1].suggestion.user_name == "Dilnoza Rahimova"
    assert first.submitted_at == clock.now()


async def test_pages_continue_with_the_cursor(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    clock: FixedClock,
) -> None:
    """LIB-13: `?cursor=` continues where the last page ended."""
    ids = []
    for i in range(3):
        ids.append(await make_pending(student, title=f"M{i}"))
        clock.advance(minutes=1)

    first, cursor = await queue(library, other_librarian, QueueTab.REVIEW, limit=2)
    assert cursor is not None
    rest, last = await queue(library, other_librarian, QueueTab.REVIEW, cursor, limit=2)

    assert [r.item.id for r in first] == ids[:2]
    assert [r.item.id for r in rest] == ids[2:]
    assert last is None


async def test_a_broken_cursor_is_a_validation_error(
    library: LibraryServices, other_librarian: Actor
) -> None:
    """LIB-13: malformed cursors answer 422, not 500."""
    with pytest.raises(ValidationFailedError):
        await queue(library, other_librarian, QueueTab.REVIEW, "not-a-cursor")


async def test_students_and_teachers_have_no_queue(
    library: LibraryServices, student: Actor, teacher: Actor
) -> None:
    """LIB-2: the queue is for librarians and Administration."""
    for actor in (student, teacher):
        with pytest.raises(ForbiddenError):
            await queue(library, actor, QueueTab.REVIEW)


async def test_a_librarian_sees_the_queue_but_not_other_peoples_drafts(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_draft: Callable[..., Awaitable[UUID]],
) -> None:
    """LIB-13: drafts are not in the queue."""
    await make_draft(student)

    rows, _ = await queue(library, other_librarian, QueueTab.REVIEW)

    assert rows == []
