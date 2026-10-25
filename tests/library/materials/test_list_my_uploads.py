"""LIB-13: `GET /me/library/uploads`: status, reason and place in the queue."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from tests.factories.library import make_book
from tests.fakes.clock import FixedClock

MakeDraft = Callable[..., Awaitable[UUID]]
MakePending = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]


async def test_uploads_are_newest_first_with_status_and_reason(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    clock: FixedClock,
) -> None:
    """LIB-13: the student sees every status and the reason with the message."""
    first = await make_draft(student, title="First")
    clock.advance(minutes=5)
    second = await make_draft(student, title="Second")
    await set_status(
        second,
        ItemStatus.CHANGES_REQUESTED,
        status_reason="low_quality",
        status_note="Add the title page",
    )

    page = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=20, locale="en"
    )

    assert [(r.item.id, r.status) for r in page.items] == [
        (second, ItemStatus.CHANGES_REQUESTED),
        (first, ItemStatus.DRAFT),
    ]
    assert page.items[0].reason == "low_quality"
    assert page.items[0].review_message == "Add the title page"
    assert page.items[1].reason is None
    assert page.next_cursor is None


async def test_queue_positions_follow_the_submission_order(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_pending: MakePending,
    clock: FixedClock,
) -> None:
    """LIB-13: position 1 is the longest waiting item of the whole queue."""
    await make_pending(other_student, title="Ahead")
    clock.advance(minutes=10)
    mine = await make_pending(student, title="Mine")

    page = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=20, locale="en"
    )

    assert [(r.item.id, r.queue_position) for r in page.items] == [(mine, 2)]


async def test_only_pending_rows_have_a_position(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
) -> None:
    """LIB-13: `queue_position` is null outside the queue."""
    await make_draft(student)

    page = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=20, locale="en"
    )

    assert [r.queue_position for r in page.items] == [None]


async def test_the_status_filter_and_paging(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: SetStatus,
    clock: FixedClock,
) -> None:
    """LIB-13: `?status=` filters; the cursor continues after the last row."""
    ids = []
    for i in range(3):
        ids.append(await make_draft(student, title=f"M{i}"))
        clock.advance(minutes=1)
    await set_status(ids[0], ItemStatus.PUBLISHED)

    drafts = await library.materials.list_my_uploads.execute(
        student, status=ItemStatus.DRAFT, cursor=None, limit=20, locale="en"
    )
    first = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=2, locale="en"
    )
    assert first.next_cursor is not None
    rest = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=first.next_cursor, limit=2, locale="en"
    )

    assert {r.item.id for r in drafts.items} == {ids[1], ids[2]}
    assert [r.item.id for r in first.items] == [ids[2], ids[1]]
    assert [r.item.id for r in rest.items] == [ids[0]]
    assert rest.next_cursor is None


async def test_nobody_else_s_uploads_or_books_are_listed(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
    store_item: Callable[..., Awaitable[object]],
) -> None:
    """LIB-13: IDOR: the list is the caller's own materials only."""
    mine = await make_draft(student)
    await make_draft(other_student)
    await store_item(make_book(owner_id=student.user_id))

    page = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=20, locale="en"
    )

    assert [r.item.id for r in page.items] == [mine]
