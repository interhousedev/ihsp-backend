"""Excuse use cases over fakes."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.academic.domain.excuses.errors import (
    ExcuseAttachmentError,
    ExcuseDocumentRequiredError,
    ExcuseInvalidError,
    ExcuseNotApprovedError,
    ExcuseNotFoundError,
    ExcuseNotPendingError,
    ExcuseNotYoursError,
)
from app.modules.academic.domain.excuses.excuse import ExcuseOrigin, ExcuseStatus
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.fakes.academic.excuses.world import ExcuseWorld

import pytest

TODAY = dt.date(2026, 10, 6)


def lesson(
    day: dt.date, *, hour: int = 9, subject_id: UUID | None = None
) -> SimpleNamespace:
    """A scheduled lesson of the student."""
    start = dt.datetime(day.year, day.month, day.day, hour, 0, tzinfo=dt.UTC)
    return SimpleNamespace(
        id=new_id(),
        date=day,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=40),
        subject_id=subject_id or new_id(),
        status="scheduled",
    )


async def request(world: ExcuseWorld, **kw: Any) -> Any:
    """Student asks with a template that needs no document."""
    args: dict[str, Any] = {
        "actor": world.student,
        "template_id": world.family.id,
        "reason": "wedding",
        "starts_on": TODAY,
        "ends_on": TODAY + dt.timedelta(days=2),
    }
    args.update(kw)
    return await world.request.execute(**args)


async def test_curator_exclusion_starts_today_open_ended(world: ExcuseWorld) -> None:
    view = await world.exclusion.execute(
        actor=world.curator,
        student_id=world.student.user_id,
        template_id=world.family.id,
    )
    excuse = view.excuse
    assert excuse.status == ExcuseStatus.APPROVED
    assert excuse.origin == ExcuseOrigin.CURATOR
    assert excuse.starts_on == TODAY
    assert excuse.ends_on is None
    assert excuse.decided_by == world.curator.user_id
    types = [n.type for n in world.notifications]
    assert types == [NotificationType.EXCUSE_DECIDED]
    assert world.notifications[0].user_id == world.student.user_id


async def test_exclusion_of_a_foreign_student_is_forbidden(world: ExcuseWorld) -> None:
    with pytest.raises(ExcuseNotYoursError):
        await world.exclusion.execute(
            actor=world.other_curator,
            student_id=world.student.user_id,
            template_id=world.family.id,
        )


async def test_admin_may_exclude_any_student(world: ExcuseWorld) -> None:
    view = await world.exclusion.execute(
        actor=world.admin,
        student_id=world.student.user_id,
        template_id=world.family.id,
        reason="  trip ",
    )
    assert view.excuse.reason == "trip"


async def test_request_is_pending_and_notifies_the_curator(world: ExcuseWorld) -> None:
    view = await request(world)
    assert view.excuse.status == ExcuseStatus.PENDING
    (note,) = world.notifications
    assert note.type == NotificationType.EXCUSE_REQUESTED
    assert note.user_id == world.curator.user_id
    assert note.payload["approve_token"] != note.payload["reject_token"]


async def test_request_without_curator_goes_to_admins(world: ExcuseWorld) -> None:
    ctx = world.directory.contexts[world.student.user_id]
    world.directory.contexts[world.student.user_id] = type(ctx)(
        ctx.student_id, ctx.group_id, None
    )
    await request(world)
    assert [n.user_id for n in world.notifications] == [world.admin.user_id]


async def test_template_requiring_a_document(world: ExcuseWorld) -> None:
    with pytest.raises(ExcuseDocumentRequiredError):
        await request(world, template_id=world.illness.id)
    file_id = world.files.add(world.student.user_id)
    view = await request(world, template_id=world.illness.id, file_ids=[file_id])
    assert view.thread[0].message.file_ids == (file_id,)


async def test_foreign_or_bad_attachment_is_rejected(world: ExcuseWorld) -> None:
    foreign = world.files.add(world.stranger.user_id)
    with pytest.raises(ExcuseAttachmentError):
        await request(world, file_ids=[foreign])
    exe = world.files.add(world.student.user_id, content_type="application/x-sh")
    with pytest.raises(ExcuseAttachmentError):
        await request(world, file_ids=[exe])


async def test_invalid_period_and_reason(world: ExcuseWorld) -> None:
    with pytest.raises(ExcuseInvalidError):
        await request(world, ends_on=TODAY - dt.timedelta(days=1))
    with pytest.raises(ExcuseInvalidError):
        await request(world, reason="  ")


async def test_approve_creates_work_offs_for_past_lessons(world: ExcuseWorld) -> None:
    yesterday = TODAY - dt.timedelta(days=1)
    past = lesson(yesterday)
    future = lesson(TODAY + dt.timedelta(days=1))
    world.schedule.lessons = [past, future]
    view = await request(world, starts_on=yesterday)
    world.notifications.clear()
    decided = await world.decide.execute(
        actor=world.curator, excuse_id=view.excuse.id, approve=True, comment="ok"
    )
    assert decided.excuse.status == ExcuseStatus.APPROVED
    assert decided.excuse.decision_comment == "ok"
    assert [w.lesson_id for w in world.work_off_rows.rows] == [past.id]
    assert [n.type for n in world.notifications] == [NotificationType.EXCUSE_DECIDED]


async def test_reject_and_double_decision(world: ExcuseWorld) -> None:
    view = await request(world)
    rejected = await world.decide.execute(
        actor=world.admin, excuse_id=view.excuse.id, approve=False
    )
    assert rejected.excuse.status == ExcuseStatus.REJECTED
    assert world.work_off_rows.rows == []
    with pytest.raises(ExcuseNotPendingError):
        await world.decide.execute(
            actor=world.admin, excuse_id=view.excuse.id, approve=True
        )


async def test_other_curator_gets_404_not_403(world: ExcuseWorld) -> None:
    view = await request(world)
    excuse_id = view.excuse.id
    with pytest.raises(ExcuseNotFoundError):
        await world.decide.execute(
            actor=world.other_curator, excuse_id=excuse_id, approve=True
        )
    with pytest.raises(ExcuseNotFoundError):
        await world.get.execute(actor=world.other_curator, excuse_id=excuse_id)
    with pytest.raises(ExcuseNotFoundError):
        await world.get.execute(actor=world.stranger, excuse_id=excuse_id)
    with pytest.raises(ExcuseNotFoundError):
        await world.cancel.execute(actor=world.stranger, excuse_id=excuse_id)
    with pytest.raises(ExcuseNotFoundError):
        await world.post.execute(actor=world.stranger, excuse_id=excuse_id, body="hi")
    with pytest.raises(ExcuseNotFoundError):
        await world.end.execute(
            actor=world.other_curator, excuse_id=excuse_id, ends_on=TODAY
        )


async def test_student_cancels_only_a_pending_request(world: ExcuseWorld) -> None:
    view = await request(world)
    cancelled = await world.cancel.execute(
        actor=world.student, excuse_id=view.excuse.id
    )
    assert cancelled.excuse.status == ExcuseStatus.CANCELLED
    with pytest.raises(ExcuseNotPendingError):
        await world.cancel.execute(actor=world.student, excuse_id=view.excuse.id)
    again = await request(world)
    await world.decide.execute(
        actor=world.curator, excuse_id=again.excuse.id, approve=True
    )
    with pytest.raises(ExcuseNotPendingError):
        await world.cancel.execute(actor=world.student, excuse_id=again.excuse.id)


async def test_end_and_revoke_an_approved_excuse(world: ExcuseWorld) -> None:
    view = await world.exclusion.execute(
        actor=world.curator,
        student_id=world.student.user_id,
        template_id=world.family.id,
    )
    ended = await world.end.execute(
        actor=world.curator, excuse_id=view.excuse.id, ends_on=TODAY
    )
    assert ended.excuse.ends_on == TODAY
    with pytest.raises(ExcuseInvalidError):
        await world.end.execute(
            actor=world.curator,
            excuse_id=view.excuse.id,
            ends_on=TODAY - dt.timedelta(days=1),
        )
    world.notifications.clear()
    revoked = await world.revoke.execute(
        actor=world.curator, excuse_id=view.excuse.id, comment="back at school"
    )
    assert revoked.excuse.status == ExcuseStatus.CANCELLED
    assert [n.type for n in world.notifications] == [NotificationType.EXCUSE_DECIDED]
    with pytest.raises(ExcuseNotApprovedError):
        await world.revoke.execute(actor=world.curator, excuse_id=view.excuse.id)


async def test_thread_between_student_curator_and_admin(world: ExcuseWorld) -> None:
    view = await request(world)
    world.notifications.clear()
    await world.post.execute(actor=world.student, excuse_id=view.excuse.id, body="hi")
    assert [n.user_id for n in world.notifications] == [world.curator.user_id]
    world.notifications.clear()
    detail = await world.post.execute(
        actor=world.curator, excuse_id=view.excuse.id, body="send a note"
    )
    assert [n.user_id for n in world.notifications] == [world.student.user_id]
    await world.post.execute(actor=world.admin, excuse_id=view.excuse.id, body="fyi")
    assert [m.message.body for m in detail.thread] == ["hi", "send a note"]
    again = await world.get.execute(actor=world.student, excuse_id=view.excuse.id)
    assert [m.author_name for m in again.thread] == ["Student", "Curator", "Admin"]
    with pytest.raises(ExcuseInvalidError):
        await world.post.execute(
            actor=world.student, excuse_id=view.excuse.id, body=" "
        )


async def test_messages_are_allowed_after_a_decision(world: ExcuseWorld) -> None:
    view = await request(world)
    await world.decide.execute(
        actor=world.curator, excuse_id=view.excuse.id, approve=False
    )
    detail = await world.post.execute(
        actor=world.student, excuse_id=view.excuse.id, body="please reconsider"
    )
    assert len(detail.thread) == 1


async def test_token_decision_is_single_use_and_user_bound(world: ExcuseWorld) -> None:
    await request(world)
    payload = world.notifications[0].payload
    roles = world.curator.roles
    with pytest.raises(ExcuseNotFoundError):
        await world.by_token.execute(
            user_id=world.other_curator.user_id,
            token=payload["approve_token"],
            roles=world.other_curator.roles,
        )
    status = await world.by_token.execute(
        user_id=world.curator.user_id, token=payload["approve_token"], roles=roles
    )
    assert status == ExcuseStatus.APPROVED
    with pytest.raises(ExcuseNotFoundError):
        await world.by_token.execute(
            user_id=world.curator.user_id, token=payload["approve_token"], roles=roles
        )
    assert world.tokens.live == {}


async def test_lists_are_scoped(world: ExcuseWorld) -> None:
    mine = await request(world)
    other = await request(world, actor=world.stranger)
    own, _ = await world.list.mine(actor=world.student, status=None, cursor=None)
    assert [v.excuse.id for v in own] == [mine.excuse.id]
    curated, _ = await world.list.staff(
        actor=world.curator, status=None, student_id=None, cursor=None
    )
    assert [v.excuse.id for v in curated] == [mine.excuse.id]
    nobody, _ = await world.list.staff(
        actor=world.curator,
        status=None,
        student_id=world.stranger.user_id,
        cursor=None,
    )
    assert nobody == []
    everyone, _ = await world.list.staff(
        actor=world.admin, status=ExcuseStatus.PENDING, student_id=None, cursor=None
    )
    assert {v.excuse.id for v in everyone} == {mine.excuse.id, other.excuse.id}
    assert [t.code for t in await world.templates.execute()] == ["illness", "family"]


async def test_coverage_by_date_lesson_and_subject(world: ExcuseWorld) -> None:
    target = lesson(TODAY)
    other = lesson(TODAY)
    await world.exclusion.execute(
        actor=world.curator,
        student_id=world.student.user_id,
        template_id=world.family.id,
        lesson_ids=[target.id],
    )
    lessons = {
        x.id: SimpleNamespace(date=x.date, id=x.id, subject_id=x.subject_id)
        for x in (target, other)
    }
    ids = [world.student.user_id]
    covered = await world.coverage.covering(
        lessons[target.id], ids  # type: ignore[arg-type]
    )
    assert list(covered) == ids
    assert (
        await world.coverage.covering(lessons[other.id], ids)  # type: ignore[arg-type]
        == {}
    )


async def test_excuse_status_query(world: ExcuseWorld) -> None:
    running = lesson(TODAY, hour=9)
    world.schedule.lessons = [running]
    at = dt.datetime(2026, 10, 6, 9, 10, tzinfo=dt.UTC)
    idle = await world.status.status(world.student.user_id, at)
    assert not idle.excused_now
    assert idle.in_lesson_time
    assert idle.curator_id == world.curator.user_id
    assert idle.group_id == world.group_id
    view = await world.exclusion.execute(
        actor=world.curator,
        student_id=world.student.user_id,
        template_id=world.family.id,
        ends_on=TODAY + dt.timedelta(days=3),
    )
    now = await world.status.status(world.student.user_id, at)
    assert now.excused_now
    assert now.excuse_id == view.excuse.id
    assert now.until == TODAY + dt.timedelta(days=3)
    await world.revoke.execute(actor=world.curator, excuse_id=view.excuse.id)
    assert not (await world.status.status(world.student.user_id, at)).excused_now
    unknown = await world.status.status(new_id(), at)
    assert unknown.curator_id is None and unknown.group_id is None
