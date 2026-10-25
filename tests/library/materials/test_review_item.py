"""LIB-13, LIB-14: librarian decisions: approve, reject, hold, restore, unpublish."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.detail import ItemDetailView
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    Approval,
    EventKind,
    ItemStatus,
    ReportReason,
    UploaderRole,
    Visibility,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ItemNotFoundError,
    OwnItemError,
    ReasonRequiredError,
)
from app.modules.library.domain.material_flow import ReviewAction
from app.modules.library.domain.moderation_entities import Report
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType
from tests.factories.library import make_book, make_external
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi
from tests.library.materials.helpers import ident

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]
MakePending = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]
StoreItem = Callable[[Item], Awaitable[Item]]


async def review(
    library: LibraryServices,
    actor: Actor,
    item_id: UUID,
    action: ReviewAction,
    reason: str | None = None,
    note: str | None = None,
) -> ItemDetailView:
    """Run one decision."""
    return await library.materials.review_item.execute(
        actor, item_id, action, reason=reason, note=note, locale="en"
    )


async def last_seq(uow_factory: UowFactory, item_id: UUID) -> int:
    """Sequence number of the newest event of the item."""
    async with uow_factory() as uow:
        return (await uow.events.history(item_id))[-1].seq


# - - - Approve - - -


async def test_another_librarian_approves_and_the_owner_is_told(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
    clock: FixedClock,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: approved -> published, with the owner notified and an audit event."""
    item_id = await make_pending(student)
    clock.advance(hours=3)
    outbox.clear()

    view = await review(library, other_librarian, item_id, ReviewAction.APPROVE)

    item = await load_item(item_id)
    assert view.status is ItemStatus.PUBLISHED
    assert item.status is ItemStatus.PUBLISHED
    assert item.published_at == clock.now()
    assert item.reviewed_by == other_librarian.user_id
    assert item.reviewed_at == clock.now()
    assert (item.status_reason, item.status_note) == (None, None)
    assert item.material is not None
    assert item.material.approval is Approval.LIBRARIAN
    seq = await last_seq(uow_factory, item_id)
    assert outbox == [
        NotificationDraft(
            user_id=student.user_id,
            type=NotificationType.LIBRARY_ITEM_APPROVED,
            payload={"item_id": str(item_id), "title": "Kinematics cheat sheet"},
            dedupe_key=f"library_item_approved:{item_id}:{seq}",
        )
    ]
    assert audit_log[-1].type == "library.approve"
    assert audit_log[-1].user_id == student.user_id
    assert audit_log[-1].actor_id == other_librarian.user_id
    assert audit_log[-1].metadata is not None
    assert audit_log[-1].metadata["item_id"] == str(item_id)


async def test_the_notification_never_names_the_reviewer(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-14: the uploader is told what happened, not who decided."""
    item_id = await make_pending(student)
    outbox.clear()

    await review(
        library, other_librarian, item_id, ReviewAction.REJECT, "duplicate", "Seen"
    )

    (note,) = outbox
    assert str(other_librarian.user_id) not in repr(note)
    assert "Malika" not in repr(note)


async def test_an_admin_approval_is_recorded_as_admin(
    library: LibraryServices,
    student: Actor,
    admin: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
) -> None:
    """LIB-13: approval `admin` when Administration decides."""
    item_id = await make_pending(student)

    await review(library, admin, item_id, ReviewAction.APPROVE)

    item = await load_item(item_id)
    assert item.material is not None and item.material.approval is Approval.ADMIN


async def test_a_librarian_cannot_approve_their_own_upload(
    library: LibraryServices,
    librarian: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
) -> None:
    """LIB-13: `library/own-item`; another librarian can."""
    item_id = await make_pending(librarian)

    with pytest.raises(OwnItemError):
        await review(library, librarian, item_id, ReviewAction.APPROVE)
    assert (await load_item(item_id)).status is ItemStatus.PENDING_REVIEW

    await review(library, other_librarian, item_id, ReviewAction.APPROVE)
    assert (await load_item(item_id)).status is ItemStatus.PUBLISHED


async def test_a_librarian_cannot_reject_or_send_back_their_own_upload(
    library: LibraryServices, librarian: Actor, make_pending: MakePending
) -> None:
    """LIB-13: no review decision on your own upload."""
    item_id = await make_pending(librarian)

    for action in (ReviewAction.REJECT, ReviewAction.REQUEST_CHANGES):
        with pytest.raises(OwnItemError):
            await review(library, librarian, item_id, action, "other")


async def test_approving_a_version_unpublishes_the_old_one(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_draft: Callable[..., Awaitable[UUID]],
    set_status: SetStatus,
    material_data: MaterialData,
    files_api: MaterialFilesApi,
    load_item: LoadItem,
) -> None:
    """LIB-13: the old version leaves when the new one is approved, not before."""
    old_id = await make_draft(student)
    await set_status(old_id, ItemStatus.PUBLISHED)
    version = await library.materials.create_material_version.execute(
        student, old_id, material_data, locale="en"
    )
    await library.materials.attach_material_files.execute(
        student, ident(version), [files_api.upload(student.user_id)], locale="en"
    )
    await library.materials.submit_material.execute(
        student, ident(version), locale="en"
    )
    assert (await load_item(old_id)).status is ItemStatus.PUBLISHED

    await review(library, other_librarian, ident(version), ReviewAction.APPROVE)

    old = await load_item(old_id)
    assert (old.status, old.status_reason) == (ItemStatus.UNPUBLISHED, "superseded")
    assert (await load_item(version.card.id)).status is ItemStatus.PUBLISHED


# - - - Request changes and reject - - -


async def test_request_changes_sends_the_message_back_to_the_student(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: changes requested with a message; the student can resubmit."""
    item_id = await make_pending(student)
    outbox.clear()

    await review(
        library,
        other_librarian,
        item_id,
        ReviewAction.REQUEST_CHANGES,
        "low_quality",
        "Add the title page",
    )

    item = await load_item(item_id)
    assert item.status is ItemStatus.CHANGES_REQUESTED
    assert (item.status_reason, item.status_note) == (
        "low_quality",
        "Add the title page",
    )
    assert item.material is not None
    assert item.material.review_message == "Add the title page"
    assert item.reviewed_by == other_librarian.user_id
    (note,) = outbox
    assert note.type is NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED
    assert note.user_id == student.user_id
    assert note.payload == {
        "item_id": str(item_id),
        "title": "Kinematics cheat sheet",
        "message": "Add the title page",
    }
    assert audit_log[-1].type == "library.request_changes"


async def test_the_message_falls_back_to_the_reason_without_a_note(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: the student always gets some text."""
    item_id = await make_pending(student)
    outbox.clear()

    await review(
        library, other_librarian, item_id, ReviewAction.REQUEST_CHANGES, "unreadable"
    )

    assert outbox[0].payload["message"] == "unreadable"


async def test_reject_keeps_the_reason_and_tells_the_owner(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: rejected with a reason code and a message."""
    item_id = await make_pending(student)
    outbox.clear()

    await review(
        library,
        other_librarian,
        item_id,
        ReviewAction.REJECT,
        "duplicate",
        "Same as M12",
    )

    item = await load_item(item_id)
    assert item.status is ItemStatus.REJECTED
    assert (item.status_reason, item.status_note) == ("duplicate", "Same as M12")
    (note,) = outbox
    assert note.type is NotificationType.LIBRARY_ITEM_REJECTED
    assert note.payload == {
        "item_id": str(item_id),
        "title": "Kinematics cheat sheet",
        "reason": "duplicate",
        "message": "Same as M12",
    }
    assert audit_log[-1].type == "library.reject"


@pytest.mark.parametrize(
    "action",
    [
        ReviewAction.REQUEST_CHANGES,
        ReviewAction.REJECT,
        ReviewAction.HOLD,
        ReviewAction.RESTORE,
        ReviewAction.UNPUBLISH,
    ],
)
@pytest.mark.parametrize("reason", [None, "", "  "])
async def test_a_decision_without_a_reason_changes_nothing(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    load_item: LoadItem,
    outbox: list[NotificationDraft],
    action: ReviewAction,
    reason: str | None,
) -> None:
    """LIB-13: every decision but approve needs a reason."""
    item_id = await make_pending(student)
    outbox.clear()

    with pytest.raises(ReasonRequiredError):
        await review(library, other_librarian, item_id, action, reason)

    assert (await load_item(item_id)).status is ItemStatus.PENDING_REVIEW
    assert outbox == []


# - - - Hold, restore, unpublish - - -


async def test_hold_hides_a_published_material_without_telling_the_owner(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    load_item: LoadItem,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: held while a librarian looks; no notification type exists for it."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED)
    outbox.clear()

    await review(
        library, librarian, item_id, ReviewAction.HOLD, "copyright", "Check source"
    )

    item = await load_item(item_id)
    assert (item.status, item.status_reason) == (ItemStatus.HELD, "copyright")
    assert outbox == []
    assert audit_log[-1].type == "library.hold"


async def test_restore_publishes_a_held_material_and_dismisses_its_reports(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    load_item: LoadItem,
    uow_factory: UowFactory,
    clock: FixedClock,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: restore closes the open reports as dismissed."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.HELD, status_reason="reported", open_reports=1)
    async with uow_factory() as uow:
        await uow.moderation.add_report(
            Report(
                id=new_id(),
                item_id=item_id,
                reporter_id=new_id(),
                reporter_role=UploaderRole.STUDENT,
                reason=ReportReason.COPYRIGHT,
                created_at=clock.now(),
            )
        )
        await uow.commit()

    await review(library, librarian, item_id, ReviewAction.RESTORE, "checked")

    item = await load_item(item_id)
    assert item.status is ItemStatus.PUBLISHED
    assert (item.status_reason, item.status_note, item.open_reports) == (None, None, 0)
    async with uow_factory() as uow:
        assert await uow.moderation.open_reports(item_id) == []
    assert audit_log[-1].type == "library.restore"
    assert audit_log[-1].metadata is not None
    assert audit_log[-1].metadata["reports_closed"] == 1


async def test_unpublish_takes_a_material_down_and_tells_the_owner(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    load_item: LoadItem,
    uow_factory: UowFactory,
    clock: FixedClock,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: takedown with a reason; open reports are upheld; the owner is told."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED, open_reports=1)
    reporter = new_id()
    async with uow_factory() as uow:
        await uow.moderation.add_report(
            Report(
                id=new_id(),
                item_id=item_id,
                reporter_id=reporter,
                reporter_role=UploaderRole.STUDENT,
                reason=ReportReason.COPYRIGHT,
                created_at=clock.now(),
            )
        )
        await uow.commit()
    outbox.clear()

    await review(
        library,
        librarian,
        item_id,
        ReviewAction.UNPUBLISH,
        "copyright",
        "Scan of a book",
    )

    item = await load_item(item_id)
    assert item.status is ItemStatus.UNPUBLISHED
    assert (item.status_reason, item.status_note) == ("copyright", "Scan of a book")
    assert item.open_reports == 0
    seq = await last_seq(uow_factory, item_id)
    assert outbox == [
        NotificationDraft(
            user_id=student.user_id,
            type=NotificationType.LIBRARY_ITEM_UNPUBLISHED,
            payload={
                "item_id": str(item_id),
                "title": "Kinematics cheat sheet",
                "reason": "copyright",
                "note": "Scan of a book",
            },
            dedupe_key=f"library_item_unpublished:{item_id}:{seq}",
        )
    ]
    assert audit_log[-1].type == "library.unpublish"
    async with uow_factory() as uow:
        assert (
            await uow.moderation.has_open_report(item_id, reporter, "copyright")
            is False
        )


async def test_a_librarian_unpublishing_their_own_item_is_not_notified(
    library: LibraryServices,
    librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-14: nobody is told about what they did themselves."""
    item_id = await make_pending(librarian)
    await set_status(item_id, ItemStatus.PUBLISHED)
    outbox.clear()

    await review(library, librarian, item_id, ReviewAction.UNPUBLISH, "mistake")

    assert outbox == []


async def test_a_librarian_cannot_restore_their_own_item(
    library: LibraryServices,
    librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
) -> None:
    """LIB-13: restore would publish it without anyone else looking."""
    item_id = await make_pending(librarian)
    await set_status(item_id, ItemStatus.UNPUBLISHED)

    with pytest.raises(OwnItemError):
        await review(library, librarian, item_id, ReviewAction.RESTORE, "oops")


async def test_a_superseded_version_cannot_be_restored(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
) -> None:
    """LIB-13: two live versions of one material would confuse readers."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.UNPUBLISHED, status_reason="superseded")

    with pytest.raises(InvalidTransitionError):
        await review(library, other_librarian, item_id, ReviewAction.RESTORE, "oops")


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (ItemStatus.PUBLISHED, ReviewAction.APPROVE),
        (ItemStatus.PUBLISHED, ReviewAction.REJECT),
        (ItemStatus.PENDING_REVIEW, ReviewAction.HOLD),
        (ItemStatus.PENDING_REVIEW, ReviewAction.UNPUBLISH),
        (ItemStatus.REJECTED, ReviewAction.RESTORE),
        (ItemStatus.HELD, ReviewAction.APPROVE),
    ],
)
async def test_illegal_arrows_are_refused_and_change_nothing(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    load_item: LoadItem,
    status: ItemStatus,
    action: ReviewAction,
) -> None:
    """LIB-13: the state machine holds at the use-case level too."""
    item_id = await make_pending(student)
    await set_status(item_id, status)

    with pytest.raises(InvalidTransitionError):
        await review(library, other_librarian, item_id, action, "reason")

    assert (await load_item(item_id)).status is status


# - - - Who may decide, and on what - - -


async def test_a_student_cannot_review(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_pending: MakePending,
) -> None:
    """LIB-2: only librarians and Administration decide."""
    item_id = await make_pending(student)

    with pytest.raises(ForbiddenError):
        await review(library, other_student, item_id, ReviewAction.APPROVE)


async def test_a_librarian_does_not_see_a_draft_or_an_unknown_item(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_draft: Callable[..., Awaitable[UUID]],
) -> None:
    """LIB-13: drafts are private; `404` for them and for unknown ids."""
    draft = await make_draft(student)

    with pytest.raises(ItemNotFoundError):
        await review(library, other_librarian, draft, ReviewAction.APPROVE)
    with pytest.raises(ItemNotFoundError):
        await review(library, other_librarian, new_id(), ReviewAction.APPROVE)


# - - - Books and UniLibrary records - - -


async def test_hold_and_unpublish_work_on_books_and_notify_the_owner(
    library: LibraryServices,
    other_librarian: Actor,
    store_item: StoreItem,
    load_item: LoadItem,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-3: a librarian can hold or unpublish a book; its creator is told."""
    creator = new_id()
    book = await store_item(make_book(owner_id=creator))

    await review(library, other_librarian, book.id, ReviewAction.HOLD, "rights")
    assert (await load_item(book.id)).status is ItemStatus.HELD
    await review(library, other_librarian, book.id, ReviewAction.UNPUBLISH, "rights")

    assert (await load_item(book.id)).status is ItemStatus.UNPUBLISHED
    assert [(n.user_id, n.type) for n in outbox] == [
        (creator, NotificationType.LIBRARY_ITEM_UNPUBLISHED)
    ]


async def test_a_book_cannot_be_approved_like_a_material(
    library: LibraryServices, other_librarian: Actor, store_item: StoreItem
) -> None:
    """LIB-3: books are published through the book endpoints."""
    book = await store_item(make_book(status=ItemStatus.PUBLISHED))

    with pytest.raises(InvalidTransitionError):
        await review(library, other_librarian, book.id, ReviewAction.APPROVE)


async def test_unpublish_hides_a_unilibrary_record_and_restore_shows_it(
    library: LibraryServices,
    other_librarian: Actor,
    store_item: StoreItem,
    load_item: LoadItem,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-12: hiding keeps the status; the record has no owner to tell."""
    record = await store_item(make_external())

    await review(
        library, other_librarian, record.id, ReviewAction.UNPUBLISH, "wrong data"
    )
    hidden = await load_item(record.id)
    await review(library, other_librarian, record.id, ReviewAction.RESTORE, "fixed")
    shown = await load_item(record.id)

    assert (hidden.status, hidden.visibility) == (
        ItemStatus.PUBLISHED,
        Visibility.HIDDEN,
    )
    assert (shown.status, shown.visibility) == (ItemStatus.PUBLISHED, Visibility.LYCEUM)
    assert outbox == []
    async with uow_factory() as uow:
        kinds = [e.kind for e in await uow.events.history(record.id)]
    assert kinds == [EventKind.HIDDEN, EventKind.RESTORED]


async def test_the_decision_is_in_the_history_with_reason_and_actor(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    make_pending: MakePending,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: `item_events` keeps who decided and why (staff-only data)."""
    item_id = await make_pending(student)

    await review(
        library,
        other_librarian,
        item_id,
        ReviewAction.REJECT,
        "off_topic",
        "Not physics",
    )

    async with uow_factory() as uow:
        event = (await uow.events.history(item_id))[-1]
    assert event.kind is EventKind.REJECTED
    assert event.actor_id == other_librarian.user_id
    assert event.data == {
        "action": "reject",
        "reason": "off_topic",
        "note": "Not physics",
    }
