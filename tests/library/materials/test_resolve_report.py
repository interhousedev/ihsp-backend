"""LIB-14: a librarian decides about the reports of an item."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemStatus,
    ReportReason,
    ReportStatus,
    SanctionKind,
    UploaderRole,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ReportNotFoundError,
)
from app.modules.library.domain.material_flow import ResolveAction
from app.modules.library.domain.moderation_entities import Report
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
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
async def reported(
    student: Actor,
    make_pending: MakePending,
    set_status: SetStatus,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> tuple[UUID, list[UUID]]:
    """A published material with three open reports (copyright twice, spam once)."""
    item_id = await make_pending(student)
    await set_status(item_id, ItemStatus.PUBLISHED, open_reports=3)
    ids = []
    async with uow_factory() as uow:
        for reason in (
            ReportReason.SPAM,
            ReportReason.COPYRIGHT,
            ReportReason.COPYRIGHT,
        ):
            report = Report(
                id=new_id(),
                item_id=item_id,
                reporter_id=new_id(),
                reporter_role=UploaderRole.STUDENT,
                reason=reason,
                created_at=clock.now(),
            )
            ids.append(report.id)
            await uow.moderation.add_report(report)
        await uow.commit()
    return item_id, ids


async def resolve(
    library: LibraryServices, actor: Actor, report_id: UUID, action: ResolveAction
) -> None:
    """Decide the reports of the item the report belongs to."""
    await library.materials.resolve_report.execute(actor, report_id, action)


async def statuses(uow_factory: UowFactory, item_id: UUID) -> set[ReportStatus]:
    """Status of every report of the item (open ones included)."""
    async with uow_factory() as uow:
        open_ones = await uow.moderation.open_reports(item_id)
        if open_ones:
            return {r.status for r in open_ones}
        return {ReportStatus.DISMISSED, ReportStatus.UPHELD}


async def test_dismiss_closes_every_report_and_keeps_a_published_item(
    library: LibraryServices,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    load_item: LoadItem,
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
    outbox: list[NotificationDraft],
) -> None:
    """LIB-14: one report id resolves all open reports of the item."""
    item_id, report_ids = reported
    outbox.clear()

    await resolve(library, other_librarian, report_ids[0], ResolveAction.DISMISS)

    item = await load_item(item_id)
    assert (item.status, item.open_reports) == (ItemStatus.PUBLISHED, 0)
    async with uow_factory() as uow:
        assert await uow.moderation.open_reports(item_id) == []
        closed = await uow.moderation.get_report(report_ids[2])
    assert closed is not None
    assert closed.status is ReportStatus.DISMISSED
    assert closed.handled_by == other_librarian.user_id
    assert closed.action == "dismiss"
    assert audit_log[-1].type == "library.report_dismiss"
    assert outbox == []


async def test_dismiss_restores_a_held_item(
    library: LibraryServices,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    set_status: SetStatus,
    load_item: LoadItem,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: dismissing the reports of a held item publishes it again."""
    item_id, report_ids = reported
    await set_status(item_id, ItemStatus.HELD, status_reason="reported")

    await resolve(library, other_librarian, report_ids[1], ResolveAction.DISMISS)

    item = await load_item(item_id)
    assert (item.status, item.status_reason) == (ItemStatus.PUBLISHED, None)
    assert audit_log[-1].type == "library.restore"


async def test_hold_hides_the_item_and_keeps_the_reports_open(
    library: LibraryServices,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    load_item: LoadItem,
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: hold while looking into it."""
    item_id, report_ids = reported

    await resolve(library, other_librarian, report_ids[0], ResolveAction.HOLD)
    await resolve(library, other_librarian, report_ids[0], ResolveAction.HOLD)

    item = await load_item(item_id)
    assert (item.status, item.status_reason) == (ItemStatus.HELD, "reported")
    async with uow_factory() as uow:
        assert len(await uow.moderation.open_reports(item_id)) == 3
    assert [a.type for a in audit_log if a.type == "library.hold"] == ["library.hold"]


async def test_unpublish_upholds_the_reports_and_tells_the_owner_the_main_reason(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    load_item: LoadItem,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: the most reported reason becomes the takedown reason."""
    item_id, report_ids = reported
    outbox.clear()

    await resolve(library, other_librarian, report_ids[0], ResolveAction.UNPUBLISH)

    item = await load_item(item_id)
    assert (item.status, item.status_reason) == (ItemStatus.UNPUBLISHED, "copyright")
    async with uow_factory() as uow:
        report = await uow.moderation.get_report(report_ids[0])
        sanctions = await uow.moderation.list_sanctions(student.user_id)
    assert report is not None and report.status is ReportStatus.UPHELD
    assert sanctions == []
    (note,) = outbox
    assert note.user_id == student.user_id
    assert note.type is NotificationType.LIBRARY_ITEM_UNPUBLISHED
    assert note.payload["reason"] == "copyright"
    assert audit_log[-1].type == "library.unpublish"


async def test_unpublish_and_warn_records_a_warning_for_the_owner(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: an upheld report can come with a warning, which is audited."""
    item_id, report_ids = reported

    await resolve(
        library, other_librarian, report_ids[0], ResolveAction.UNPUBLISH_AND_WARN
    )

    async with uow_factory() as uow:
        (warning,) = await uow.moderation.list_sanctions(student.user_id)
    assert warning.kind is SanctionKind.WARNING
    assert warning.item_id == item_id
    assert warning.set_by == other_librarian.user_id
    assert warning.until is None
    assert [a.type for a in audit_log[-2:]] == ["library.unpublish", "library.sanction"]
    assert audit_log[-1].user_id == student.user_id


async def test_unilibrary_records_are_hidden_not_unpublished(
    library: LibraryServices,
    other_librarian: Actor,
    store_item: StoreItem,
    load_item: LoadItem,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-12: upholding a report about a record hides it and closes the reports."""
    record = await store_item(make_external())
    report = Report(
        id=new_id(),
        item_id=record.id,
        reporter_id=new_id(),
        reporter_role=UploaderRole.STUDENT,
        reason=ReportReason.WRONG_CONTENT,
        created_at=clock.now(),
    )
    async with uow_factory() as uow:
        await uow.moderation.add_report(report)
        await uow.commit()

    await resolve(library, other_librarian, report.id, ResolveAction.UNPUBLISH_AND_WARN)

    item = await load_item(record.id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.visibility.value == "hidden"
    async with uow_factory() as uow:
        assert await uow.moderation.open_reports(record.id) == []
        assert await uow.moderation.list_sanctions() == []


async def test_a_resolved_report_is_a_no_op_the_second_time(
    library: LibraryServices,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    load_item: LoadItem,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: a stale double click does no harm."""
    item_id, report_ids = reported
    await resolve(library, other_librarian, report_ids[0], ResolveAction.DISMISS)
    audits = len(audit_log)

    await resolve(library, other_librarian, report_ids[1], ResolveAction.UNPUBLISH)

    assert (await load_item(item_id)).status is ItemStatus.PUBLISHED
    assert len(audit_log) == audits


async def test_an_unknown_report_is_not_found(
    library: LibraryServices, other_librarian: Actor
) -> None:
    """LIB-14: `404` for a missing report."""
    with pytest.raises(ReportNotFoundError):
        await resolve(library, other_librarian, new_id(), ResolveAction.DISMISS)


async def test_unpublishing_an_already_withdrawn_item_is_refused(
    library: LibraryServices,
    other_librarian: Actor,
    reported: tuple[UUID, list[UUID]],
    set_status: SetStatus,
) -> None:
    """LIB-14: the owner withdrew it meanwhile; there is nothing left to take down."""
    item_id, report_ids = reported
    await set_status(item_id, ItemStatus.UNPUBLISHED)

    with pytest.raises(InvalidTransitionError):
        await resolve(library, other_librarian, report_ids[0], ResolveAction.UNPUBLISH)


async def test_only_librarians_resolve_reports(
    library: LibraryServices,
    teacher: Actor,
    reported: tuple[UUID, list[UUID]],
) -> None:
    """LIB-2: a teacher can report but not decide."""
    _, report_ids = reported

    with pytest.raises(ForbiddenError):
        await resolve(library, teacher, report_ids[0], ResolveAction.DISMISS)
