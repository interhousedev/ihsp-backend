"""LIB-14: reporting an item, the daily limit and the automatic hold."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    EventKind,
    ItemStatus,
    ReportReason,
    UploaderRole,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ItemNotFoundError,
    LibraryRateLimitedError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType
from tests.factories.library import make_external
from tests.fakes.clock import FixedClock

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]
MakePending = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]
StoreItem = Callable[[Item], Awaitable[Item]]


@pytest.fixture
async def published_id(
    student: Actor, make_pending: MakePending, set_status: SetStatus
) -> UUID:
    """A published material of the student."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    return item_id


async def report(
    library: LibraryServices,
    actor: Actor,
    item_id: UUID,
    reason: ReportReason = ReportReason.COPYRIGHT,
    text: str | None = None,
) -> None:
    """File one report."""
    await library.materials.report_item.execute(actor, item_id, reason, text)


async def test_a_student_report_is_stored_without_hiding_the_item(
    library: LibraryServices,
    other_student: Actor,
    published_id: UUID,
    load_item: LoadItem,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-14: one student report enters the queue; the item stays visible."""
    outbox.clear()

    await report(
        library,
        other_student,
        published_id,
        ReportReason.WRONG_CONTENT,
        " Wrong formula ",
    )

    item = await load_item(published_id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.open_reports == 1
    async with uow_factory() as uow:
        (stored,) = await uow.moderation.open_reports(published_id)
    assert stored.reporter_id == other_student.user_id
    assert stored.reporter_role is UploaderRole.STUDENT
    assert stored.reason is ReportReason.WRONG_CONTENT
    assert stored.text == "Wrong formula"
    assert outbox == []


async def test_two_students_with_serious_reasons_hold_the_item_and_alert_librarians(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    librarian: Actor,
    other_librarian: Actor,
    admin: Actor,
    make_actor: Callable[..., Actor],
    published_id: UUID,
    load_item: LoadItem,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: the second distinct reporter holds it; each librarian hears once."""
    outbox.clear()
    await report(library, other_student, published_id, ReportReason.COPYRIGHT)
    assert outbox == []

    await report(
        library, make_actor(Role.STUDENT), published_id, ReportReason.EXAM_LEAK
    )

    item = await load_item(published_id)
    assert (item.status, item.status_reason) == (ItemStatus.HELD, "reported")
    async with uow_factory() as uow:
        history = await uow.events.history(published_id)
    held = history[-1]
    assert held.kind is EventKind.HELD
    assert held.actor_id is None
    assert held.data["auto"] is True
    recipients = {n.user_id for n in outbox}
    assert recipients == {librarian.user_id, other_librarian.user_id, admin.user_id}
    assert all(n.type is NotificationType.LIBRARY_REPORT_FILED for n in outbox)
    assert {n.dedupe_key for n in outbox} == {
        f"library_report_filed:{n.user_id}:{published_id}:{held.seq}" for n in outbox
    }
    assert outbox[0].payload == {
        "item_id": str(published_id),
        "title": "Kinematics cheat sheet",
        "reason": "exam_leak",
    }
    assert audit_log[-1].type == "library.hold"
    assert audit_log[-1].actor_id is None
    assert audit_log[-1].user_id == student.user_id


async def test_a_librarian_who_reports_is_not_alerted_about_their_own_report(
    library: LibraryServices,
    librarian: Actor,
    other_librarian: Actor,
    published_id: UUID,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-14: the alert goes to the other librarians."""
    outbox.clear()

    await report(library, librarian, published_id, ReportReason.COPYRIGHT)

    assert [n.user_id for n in outbox if n.user_id == librarian.user_id] == []
    assert other_librarian.user_id in {n.user_id for n in outbox}


async def test_the_same_reporter_twice_counts_once(
    library: LibraryServices,
    other_student: Actor,
    published_id: UUID,
    load_item: LoadItem,
) -> None:
    """LIB-14: two reasons from one person are one reporter."""
    await report(library, other_student, published_id, ReportReason.COPYRIGHT)
    await report(library, other_student, published_id, ReportReason.EXAM_LEAK)

    item = await load_item(published_id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.open_reports == 2


async def test_repeating_the_same_report_changes_nothing(
    library: LibraryServices,
    other_student: Actor,
    published_id: UUID,
    load_item: LoadItem,
    uow_factory: UowFactory,
) -> None:
    """LIB-14: one open report per item, reporter and reason; the repeat is a no-op."""
    await report(library, other_student, published_id)
    await report(library, other_student, published_id)

    assert (await load_item(published_id)).open_reports == 1
    async with uow_factory() as uow:
        assert len(await uow.moderation.open_reports(published_id)) == 1


async def test_mild_reasons_never_hold(
    library: LibraryServices,
    other_student: Actor,
    make_actor: Callable[..., Actor],
    published_id: UUID,
    load_item: LoadItem,
) -> None:
    """LIB-14: spam and wrong content from many students only fill the queue."""
    students = [other_student, make_actor(Role.STUDENT), make_actor(Role.STUDENT)]
    for who in students:
        await report(library, who, published_id, ReportReason.SPAM)

    item = await load_item(published_id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.open_reports == 3


@pytest.mark.parametrize("who", ["teacher", "librarian", "admin"])
async def test_one_report_from_staff_holds_at_once(
    library: LibraryServices,
    published_id: UUID,
    load_item: LoadItem,
    request: pytest.FixtureRequest,
    who: str,
) -> None:
    """LIB-14: one report from a teacher, librarian or admin."""
    reporter: Actor = request.getfixturevalue(who)

    await report(library, reporter, published_id, ReportReason.WRONG_CONTENT)

    assert (await load_item(published_id)).status is ItemStatus.HELD


async def test_the_hold_threshold_follows_the_setting(
    build_library: Callable[..., LibraryServices],
    other_student: Actor,
    make_actor: Callable[..., Actor],
    published_id: UUID,
    load_item: LoadItem,
) -> None:
    """LIB-14: LIBRARY__AUTO_HOLD_REPORTERS=3 needs three reporters."""
    strict = build_library(auto_hold_reporters=3)
    await report(strict, other_student, published_id)
    await report(strict, make_actor(Role.STUDENT), published_id)
    assert (await load_item(published_id)).status is ItemStatus.PUBLISHED

    await report(strict, make_actor(Role.STUDENT), published_id)

    assert (await load_item(published_id)).status is ItemStatus.HELD


async def test_the_uploader_never_sees_who_reported(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    published_id: UUID,
) -> None:
    """LIB-14: the reporter is invisible in everything the owner can read."""
    await report(
        library, other_student, published_id, ReportReason.COPYRIGHT, "secret text"
    )

    uploads = await library.materials.list_my_uploads.execute(
        student, status=None, cursor=None, limit=20, locale="en"
    )

    shown = repr(uploads)
    assert str(other_student.user_id) not in shown
    assert "secret text" not in shown
    assert "Bobur" not in shown


async def test_owners_cannot_report_their_own_item(
    library: LibraryServices, student: Actor, published_id: UUID
) -> None:
    """LIB-14: reporting your own upload is refused."""
    with pytest.raises(ForbiddenError):
        await report(library, student, published_id)


async def test_an_invisible_item_is_not_found(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_draft: Callable[..., Awaitable[UUID]],
) -> None:
    """LIB-14: IDOR: a draft of somebody else looks like a missing item."""
    draft = await make_draft(student)

    with pytest.raises(ItemNotFoundError):
        await report(library, other_student, draft)
    with pytest.raises(ItemNotFoundError):
        await report(library, other_student, new_id())


async def test_only_published_items_can_be_reported(
    library: LibraryServices,
    other_librarian: Actor,
    published_id: UUID,
    set_status: SetStatus,
) -> None:
    """LIB-14: a librarian who can see a held item cannot report it again."""
    await set_status(published_id, ItemStatus.HELD)

    with pytest.raises(InvalidTransitionError):
        await report(library, other_librarian, published_id)


async def test_reports_on_unilibrary_records_never_hold_them(
    library: LibraryServices,
    teacher: Actor,
    store_item: StoreItem,
    load_item: LoadItem,
) -> None:
    """LIB-12: a wrong record is reported to the queue; the sync owns its status."""
    record = await store_item(make_external())

    await report(library, teacher, record.id, ReportReason.WRONG_CONTENT)

    item = await load_item(record.id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.open_reports == 1


async def test_the_text_is_limited_to_five_hundred_characters(
    library: LibraryServices, other_student: Actor, published_id: UUID
) -> None:
    """LIB-14: at most 500 characters."""
    with pytest.raises(ValidationFailedError) as caught:
        await report(library, other_student, published_id, text="x" * 501)

    assert caught.value.params == {"field": "text"}


async def test_the_daily_limit_resets_with_the_clock(
    build_library: Callable[..., LibraryServices],
    other_student: Actor,
    student: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    clock: FixedClock,
) -> None:
    """LIB-14: 10 reports a day by default; `resets_at` names the end of the wait."""
    strict = build_library(limit_reports_day=2)
    ids = []
    for _ in range(3):
        item_id = await make_pending(student)
        await set_status(item_id, ItemStatus.PUBLISHED)
        ids.append(item_id)
    first_at = clock.now()
    await report(strict, other_student, ids[0], ReportReason.SPAM)
    clock.advance(hours=2)
    await report(strict, other_student, ids[1], ReportReason.SPAM)

    with pytest.raises(LibraryRateLimitedError) as caught:
        await report(strict, other_student, ids[2], ReportReason.SPAM)

    assert caught.value.params["action"] == "report"
    assert caught.value.params["limit"] == 2
    assert datetime.fromisoformat(caught.value.params["resets_at"]) == (
        first_at + timedelta(days=1)
    ).astimezone(UTC)
    clock.set(first_at + timedelta(days=1, minutes=1))
    await report(strict, other_student, ids[2], ReportReason.SPAM)
