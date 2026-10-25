"""LIB-13: submitting a material: the queue, auto-publishing, limits and bans."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialPatch
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    Approval,
    EventKind,
    ItemStatus,
    SanctionKind,
)
from app.modules.library.domain.errors import (
    AttestationRequiredError,
    InvalidTransitionError,
    ItemNotFoundError,
    LibraryRateLimitedError,
    NoFilesError,
    UploadBannedError,
)
from app.modules.library.domain.moderation_entities import Sanction
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.fakes.clock import FixedClock

import pytest

LoadItem = Callable[[UUID | None], Awaitable[Item]]
MakeDraft = Callable[..., Awaitable[UUID]]


async def test_a_student_submit_goes_to_the_queue(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
    clock: FixedClock,
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: pending review, with the submission time and no approval yet."""
    item_id = await make_draft(student)

    view = await library.materials.submit_material.execute(
        student, item_id, locale="en"
    )

    item = await load_item(item_id)
    assert view.status is ItemStatus.PENDING_REVIEW
    assert item.status is ItemStatus.PENDING_REVIEW
    assert item.material is not None
    assert item.material.submitted_at == clock.now()
    assert item.material.approval is None
    assert item.published_at is None
    async with uow_factory() as uow:
        history = await uow.events.history(item_id)
    assert [e.kind for e in history] == [
        EventKind.CREATED,
        EventKind.EDITED,
        EventKind.SUBMITTED,
    ]
    assert audit_log == []


async def test_a_teacher_submit_publishes_at_once_and_is_audited(
    library: LibraryServices,
    teacher: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
    clock: FixedClock,
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: auto-approved by role; the audit log records `library.auto_approve`."""
    item_id = await make_draft(teacher)

    view = await library.materials.submit_material.execute(
        teacher, item_id, locale="en"
    )

    item = await load_item(item_id)
    assert view.status is ItemStatus.PUBLISHED
    assert item.status is ItemStatus.PUBLISHED
    assert item.published_at == clock.now()
    assert item.material is not None
    assert item.material.approval is Approval.AUTO_TEACHER
    assert item.reviewed_by is None
    async with uow_factory() as uow:
        history = await uow.events.history(item_id)
    assert [e.kind for e in history][-2:] == [EventKind.SUBMITTED, EventKind.APPROVED]
    assert history[-1].data == {"auto": True, "approval": "auto_teacher"}
    assert [(a.type, a.user_id, a.actor_id) for a in audit_log] == [
        ("library.auto_approve", teacher.user_id, teacher.user_id)
    ]
    assert audit_log[0].metadata == {
        "item_id": str(item_id),
        "approval": "auto_teacher",
    }


async def test_teacher_review_setting_queues_teacher_uploads(
    build_library: Callable[..., LibraryServices],
    teacher: Actor,
    make_draft: MakeDraft,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-13: LIBRARY__TEACHER_REVIEW=true sends teachers through the queue."""
    strict = build_library(teacher_review=True)
    item_id = await make_draft(teacher, services=strict)

    view = await strict.materials.submit_material.execute(teacher, item_id, locale="en")

    assert view.status is ItemStatus.PENDING_REVIEW
    assert audit_log == []


async def test_an_admin_submit_publishes_with_approval_admin(
    library: LibraryServices, admin: Actor, make_draft: MakeDraft, load_item: LoadItem
) -> None:
    """LIB-13: Administration publishes directly."""
    item_id = await make_draft(admin)

    await library.materials.submit_material.execute(admin, item_id, locale="en")

    item = await load_item(item_id)
    assert item.status is ItemStatus.PUBLISHED
    assert item.material is not None and item.material.approval is Approval.ADMIN


async def test_a_librarian_submit_waits_for_another_librarian(
    library: LibraryServices, librarian: Actor, make_draft: MakeDraft
) -> None:
    """LIB-13: nobody approves their own upload."""
    item_id = await make_draft(librarian)

    view = await library.materials.submit_material.execute(
        librarian, item_id, locale="en"
    )

    assert view.status is ItemStatus.PENDING_REVIEW


async def test_a_material_without_file_or_text_cannot_be_submitted(
    library: LibraryServices, student: Actor, make_draft: MakeDraft
) -> None:
    """LIB-13: add a file or write the text first."""
    item_id = await make_draft(student, with_file=False)

    with pytest.raises(NoFilesError):
        await library.materials.submit_material.execute(student, item_id, locale="en")


async def test_submit_needs_the_attestation_which_can_be_given_with_a_patch(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    load_item: LoadItem,
) -> None:
    """LIB-13: a draft saved with `attested=false` cannot be submitted until ticked."""
    item_id = await make_draft(student, attested=False)

    with pytest.raises(AttestationRequiredError):
        await library.materials.submit_material.execute(student, item_id, locale="en")
    await library.materials.update_material.execute(
        student, item_id, MaterialPatch(attested=True), locale="en"
    )
    view = await library.materials.submit_material.execute(
        student, item_id, locale="en"
    )

    assert view.status is ItemStatus.PENDING_REVIEW
    assert (await load_item(item_id)).status is ItemStatus.PENDING_REVIEW


async def test_a_written_text_is_enough_to_submit(
    library: LibraryServices, student: Actor, make_draft: MakeDraft
) -> None:
    """LIB-13: a markdown body counts as the content."""
    item_id = await make_draft(student, with_file=False, body_md="# Notes")

    view = await library.materials.submit_material.execute(
        student, item_id, locale="en"
    )

    assert view.status is ItemStatus.PENDING_REVIEW


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.PENDING_REVIEW,
        ItemStatus.PUBLISHED,
        ItemStatus.HELD,
        ItemStatus.REJECTED,
        ItemStatus.UNPUBLISHED,
    ],
)
async def test_only_a_draft_or_a_sent_back_material_can_be_submitted(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: Callable[..., Awaitable[None]],
    status: ItemStatus,
) -> None:
    """LIB-13: there is no other submit arrow."""
    item_id = await make_draft(student)
    await set_status(item_id, status)

    with pytest.raises(InvalidTransitionError):
        await library.materials.submit_material.execute(student, item_id, locale="en")


async def test_resubmitting_after_changes_clears_the_old_reason(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    set_status: Callable[..., Awaitable[None]],
    load_item: LoadItem,
) -> None:
    """LIB-13: request changes -> resubmit goes back to the queue, clean."""
    item_id = await make_draft(student)
    await set_status(
        item_id,
        ItemStatus.CHANGES_REQUESTED,
        status_reason="low_quality",
        status_note="Add the title page",
    )

    view = await library.materials.submit_material.execute(
        student, item_id, locale="en"
    )

    item = await load_item(item_id)
    assert view.status is ItemStatus.PENDING_REVIEW
    assert (item.status_reason, item.status_note) == (None, None)


async def test_somebody_elses_draft_is_not_found(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
) -> None:
    """LIB-13: IDOR: `404`, never `403`."""
    item_id = await make_draft(student)

    with pytest.raises(ItemNotFoundError):
        await library.materials.submit_material.execute(
            other_student, item_id, locale="en"
        )


async def test_a_banned_user_cannot_submit(
    library: LibraryServices,
    student: Actor,
    make_draft: MakeDraft,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-14: a ban set after the draft was made still stops the submit."""
    item_id = await make_draft(student)
    async with uow_factory() as uow:
        await uow.moderation.add_sanction(
            Sanction(
                id=new_id(),
                user_id=student.user_id,
                kind=SanctionKind.UPLOAD_BAN,
                reason="repeated copyright reports",
                set_by=new_id(),
                created_at=clock.now(),
                until=None,
            )
        )
        await uow.commit()

    with pytest.raises(UploadBannedError) as caught:
        await library.materials.submit_material.execute(student, item_id, locale="en")

    assert caught.value.params == {"until": None}


# - - - Limits - - -


async def test_the_daily_limit_blocks_and_the_clock_reopens_it(
    build_library: Callable[..., LibraryServices],
    student: Actor,
    make_pending: Callable[..., Awaitable[UUID]],
    make_draft: MakeDraft,
    clock: FixedClock,
) -> None:
    """LIB-13: 10 a day for students; `resets_at` says when the oldest ages out."""
    strict = build_library(limit_uploads_day_student=2)
    first_at = clock.now()
    await make_pending(student, services=strict)
    clock.advance(hours=1)
    await make_pending(student, services=strict)
    clock.advance(hours=1)
    third = await make_draft(student, services=strict)

    with pytest.raises(LibraryRateLimitedError) as caught:
        await strict.materials.submit_material.execute(student, third, locale="en")

    assert caught.value.params["action"] == "upload"
    assert caught.value.params["limit"] == 2
    expected = (first_at + timedelta(days=1)).astimezone(UTC)
    assert datetime.fromisoformat(caught.value.params["resets_at"]) == expected
    clock.set(first_at + timedelta(days=1, minutes=1))
    view = await strict.materials.submit_material.execute(student, third, locale="en")
    assert view.status is ItemStatus.PENDING_REVIEW


async def test_the_weekly_limit_blocks_students(
    build_library: Callable[..., LibraryServices],
    student: Actor,
    make_pending: Callable[..., Awaitable[UUID]],
    make_draft: MakeDraft,
    clock: FixedClock,
) -> None:
    """LIB-13: 40 a week for students, even when each day is below its limit."""
    strict = build_library(limit_uploads_day_student=10, limit_uploads_week_student=3)
    for _ in range(3):
        await make_pending(student, services=strict)
        clock.advance(days=1, minutes=1)
    fourth = await make_draft(student, services=strict)

    with pytest.raises(LibraryRateLimitedError) as caught:
        await strict.materials.submit_material.execute(student, fourth, locale="en")

    assert caught.value.params["limit"] == 3


async def test_teacher_limits_differ_from_student_limits(
    build_library: Callable[..., LibraryServices],
    teacher: Actor,
    make_draft: MakeDraft,
) -> None:
    """LIB-13: teachers have their own daily limit (30 by default)."""
    strict = build_library(limit_uploads_day_teacher=1, limit_uploads_day_student=50)
    first = await make_draft(teacher, services=strict)
    second = await make_draft(teacher, services=strict)
    await strict.materials.submit_material.execute(teacher, first, locale="en")

    with pytest.raises(LibraryRateLimitedError) as caught:
        await strict.materials.submit_material.execute(teacher, second, locale="en")

    assert caught.value.params["limit"] == 1


@pytest.mark.parametrize("who", ["librarian", "admin"])
async def test_librarians_and_admins_are_not_rate_limited(
    build_library: Callable[..., LibraryServices],
    make_draft: MakeDraft,
    request: pytest.FixtureRequest,
    who: str,
) -> None:
    """LIB-13: staff who run the library have no upload limit."""
    actor: Actor = request.getfixturevalue(who)
    strict = build_library(limit_uploads_day_student=1, limit_uploads_day_teacher=1)
    ids = [await make_draft(actor, services=strict) for _ in range(3)]

    for item_id in ids:
        await strict.materials.submit_material.execute(actor, item_id, locale="en")


async def test_a_resubmission_does_not_count_against_itself(
    build_library: Callable[..., LibraryServices],
    student: Actor,
    make_draft: MakeDraft,
    set_status: Callable[..., Awaitable[None]],
) -> None:
    """LIB-13: at the limit, a sent-back material can still be resubmitted."""
    strict = build_library(limit_uploads_day_student=1)
    item_id = await make_draft(student, services=strict)
    await strict.materials.submit_material.execute(student, item_id, locale="en")
    await set_status(item_id, ItemStatus.CHANGES_REQUESTED)

    view = await strict.materials.submit_material.execute(student, item_id, locale="en")

    assert view.status is ItemStatus.PENDING_REVIEW
