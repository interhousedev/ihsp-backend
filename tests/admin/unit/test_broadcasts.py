"""Broadcast use cases (ADM-11, BOT-21, UF-ADM-08)."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.admin.application.audience_count import AudienceCount
from app.modules.admin.application.broadcast_view import (
    BroadcastPresenter,
    BroadcastView,
)
from app.modules.admin.application.cancel_broadcast import CancelBroadcast
from app.modules.admin.application.create_broadcast import CreateBroadcast
from app.modules.admin.application.deliver_broadcast import DeliverBroadcast
from app.modules.admin.application.finish_broadcasts import FinishBroadcasts
from app.modules.admin.application.get_broadcast import GetBroadcast
from app.modules.admin.application.list_broadcasts import ListBroadcasts
from app.modules.admin.application.preview_broadcast import PreviewBroadcast
from app.modules.admin.application.resolve_audience import ResolveAudience
from app.modules.admin.application.send_broadcast import SendBroadcast
from app.modules.admin.application.start_scheduled_broadcasts import (
    StartScheduledBroadcasts,
)
from app.modules.admin.application.update_broadcast import (
    BroadcastPatch,
    UpdateBroadcast,
)
from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import BroadcastStatus, CreatedVia
from app.modules.admin.domain.errors import (
    BroadcastEmptyAudienceError,
    BroadcastNotCancellableError,
    BroadcastNotEditableError,
    BroadcastNoTelegramError,
    BroadcastNotSendableError,
    BroadcastTextTooLongError,
    BroadcastTimeInvalidError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.identity import UserRef, UserStatus
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.admin.fakes import AdminWorld
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.schedule import FakeScheduleQueries

import pytest

ADMIN_TELEGRAM_ID = 900


class Admin:
    """Broadcast use cases over in-memory fakes."""

    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.world = AdminWorld()
        self.identity = FakeIdentityDirectory()
        self.schedule = FakeScheduleQueries()
        self.admin_user = self.identity.add_user(
            make_user(Role.ADMIN, first_name="Gulnora"), ADMIN_TELEGRAM_ID
        )
        self.actor = Actor(user_id=self.admin_user.id, roles=frozenset({Role.ADMIN}))
        uow = self.world.uow
        presenter = BroadcastPresenter(self.identity)
        self.resolver = ResolveAudience(self.identity, self.schedule)
        deliver = DeliverBroadcast(uow_factory=uow)
        self.create = CreateBroadcast(uow_factory=uow, presenter=presenter, clock=clock)
        self.update = UpdateBroadcast(uow_factory=uow, presenter=presenter)
        self.get = GetBroadcast(uow_factory=uow, presenter=presenter)
        self.list = ListBroadcasts(uow_factory=uow, presenter=presenter)
        self.count = AudienceCount(self.resolver)
        self.cancel = CancelBroadcast(uow_factory=uow, presenter=presenter)
        self.preview = PreviewBroadcast(uow_factory=uow, identity=self.identity)
        self.send = SendBroadcast(
            uow_factory=uow,
            resolver=self.resolver,
            deliver=deliver,
            presenter=presenter,
            clock=clock,
        )
        self.start_scheduled = StartScheduledBroadcasts(
            uow_factory=uow, resolver=self.resolver, deliver=deliver, clock=clock
        )
        self.finish = FinishBroadcasts(
            uow_factory=uow, resolver=self.resolver, deliver=deliver
        )

    def students(self, count: int, **kwargs: Any) -> list[UserRef]:
        return [
            self.identity.add_user(make_user(Role.STUDENT, **kwargs), 1000 + i)
            for i in range(count)
        ]

    async def draft(
        self, audience: Audience | None = None, text: str = "<b>Hello</b>"
    ) -> BroadcastView:
        return await self.create.execute(
            self.actor,
            title="Exams",
            text=text,
            media_file_ids=[],
            audience=audience or Audience(roles=[Role.STUDENT]),
        )

    def status(self, broadcast_id: UUID) -> BroadcastStatus:
        return self.world.broadcasts.rows[broadcast_id].status


@pytest.fixture
def adm(clock: FixedClock) -> Admin:
    return Admin(clock)


# - - - Drafts - - -


async def test_draft_is_saved_with_clean_html_and_the_author(adm: Admin) -> None:
    """ADM-11: formatting is kept, unsupported markup is removed."""
    view = await adm.draft(text="<script>alert(1)</script><b>Hi</b><br><u>all</u>")

    b = view.broadcast
    assert b.status == BroadcastStatus.DRAFT
    assert b.created_via == CreatedVia.UI
    assert b.text == "<b>Hi</b>\n<u>all</u>"
    assert b.author_id == adm.actor.user_id
    assert view.author is not None and view.author.first_name == "Gulnora"
    assert view.stats is None


async def test_assistant_can_create_drafts_only_marked_as_assistant(
    adm: Admin,
) -> None:
    """UF-ADM-08 alternative 1a: the draft says it came from the assistant."""
    view = await adm.create.execute(
        adm.actor,
        title="T",
        text="x",
        media_file_ids=[],
        audience=Audience(everyone=True),
        created_via=CreatedVia.ASSISTANT,
    )

    assert view.broadcast.created_via == CreatedVia.ASSISTANT
    assert view.broadcast.status == BroadcastStatus.DRAFT


async def test_text_that_does_not_fit_one_telegram_message_is_refused(
    adm: Admin,
) -> None:
    """Telegram allows 4096 characters per message."""
    with pytest.raises(BroadcastTextTooLongError):
        await adm.draft(text="x" * 4000)


async def test_only_administration_can_use_broadcasts(adm: Admin) -> None:
    """GEN-7: a teacher cannot create broadcasts."""
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))

    with pytest.raises(ForbiddenError):
        await adm.create.execute(
            teacher, title="T", text="x", media_file_ids=[], audience=Audience()
        )


async def test_draft_can_be_edited_but_a_sending_broadcast_cannot(adm: Admin) -> None:
    """UF-ADM-08: edit until it starts."""
    adm.students(1)
    view = await adm.draft()
    bid = view.broadcast.id

    edited = await adm.update.execute(
        adm.actor, bid, BroadcastPatch(title="New title", text="<i>new</i>")
    )
    assert (edited.broadcast.title, edited.broadcast.text) == (
        "New title",
        "<i>new</i>",
    )

    await adm.send.execute(adm.actor, bid)
    with pytest.raises(BroadcastNotEditableError):
        await adm.update.execute(adm.actor, bid, BroadcastPatch(title="Late"))


# - - - Audience - - -


async def test_audience_is_the_union_of_roles_groups_and_semesters(
    adm: Admin,
) -> None:
    """ADM-11, UF-ADM-08 step 2: roles + groups + semesters, each person once."""
    teacher = adm.identity.add_user(make_user(Role.TEACHER), 1)
    in_group, in_both, in_semester = adm.students(3)
    group_id = new_id()
    adm.schedule.group_users[group_id] = [in_group.id, in_both.id]
    adm.schedule.semester_users[2] = [in_both.id, in_semester.id]
    audience = Audience(roles=[Role.TEACHER], group_ids=[group_id], semesters=[2])

    ids = await adm.resolver.execute(audience)
    count = await adm.count.execute(adm.actor, audience)

    assert ids == {teacher.id, in_group.id, in_both.id, in_semester.id}
    assert count == 4


async def test_everyone_means_all_active_users_with_a_role(adm: Admin) -> None:
    """ADM-11: everyone = student, teacher, admin and lms_admin, active only."""
    students = adm.students(2)
    adm.students(1, status=UserStatus.BLOCKED)
    teacher = adm.identity.add_user(make_user(Role.TEACHER), 5)
    lms = adm.identity.add_user(make_user(Role.LMS_ADMIN), 6)

    ids = await adm.resolver.execute(Audience(everyone=True))

    assert ids == {
        adm.admin_user.id,
        teacher.id,
        lms.id,
        *(s.id for s in students),
    }


async def test_blocked_users_are_not_recipients_of_a_role_audience(
    adm: Admin,
) -> None:
    """BOT-22 / GEN-7: only active accounts receive broadcasts."""
    active = adm.students(1)[0]
    adm.students(2, status=UserStatus.DEACTIVATED)

    ids = await adm.resolver.execute(Audience(roles=[Role.STUDENT]))

    assert ids == {active.id}


# - - - Sending - - -


async def test_send_now_writes_one_notification_per_recipient_and_audits(
    adm: Admin,
) -> None:
    """BOT-21, UF-ADM-08 step 5: one `broadcast` notification each, audit logged."""
    students = adm.students(3)
    view = await adm.draft()
    bid = view.broadcast.id

    sent = await adm.send.execute(adm.actor, bid)

    drafts = adm.world.outbox
    assert {d.user_id for d in drafts} == {s.id for s in students}
    assert {d.dedupe_key for d in drafts} == {f"bc:{bid}:{s.id}" for s in students}
    assert all(
        d.type == NotificationType.BROADCAST and d.broadcast_id == bid for d in drafts
    )
    assert drafts[0].payload == {
        "broadcast_id": str(bid),
        "title": "Exams",
        "text": "<b>Hello</b>",
        "media_file_ids": [],
    }
    assert sent.broadcast.status == BroadcastStatus.SENDING
    assert sent.stats is not None and sent.stats.total == 3
    (audit,) = adm.world.audits
    assert audit.type == "broadcast.sent"
    assert audit.actor_id == adm.actor.user_id
    assert audit.metadata == {
        "broadcast_id": str(bid),
        "author_id": str(adm.actor.user_id),
        "recipients": 3,
    }


async def test_notifications_are_written_in_batches_of_1000(adm: Admin) -> None:
    """ADM-11: large audiences don't build one huge transaction."""
    adm.students(2500)
    view = await adm.draft()

    await adm.send.execute(adm.actor, view.broadcast.id)

    assert adm.world.batches == [1000, 1000, 500]
    assert len({d.dedupe_key for d in adm.world.outbox}) == 2500


async def test_future_time_schedules_instead_of_sending(adm: Admin) -> None:
    """UF-ADM-08 step 4: a scheduled broadcast sends nothing yet."""
    adm.students(2)
    view = await adm.draft()
    at = adm.clock.now() + timedelta(hours=2)

    scheduled = await adm.send.execute(adm.actor, view.broadcast.id, at)

    assert scheduled.broadcast.status == BroadcastStatus.SCHEDULED
    assert scheduled.broadcast.scheduled_at == at
    assert adm.world.outbox == []


async def test_time_in_the_past_sends_now(adm: Admin) -> None:
    """UF-ADM-08: a past time means send now."""
    adm.students(1)
    view = await adm.draft()

    sent = await adm.send.execute(
        adm.actor, view.broadcast.id, adm.clock.now() - timedelta(minutes=1)
    )

    assert sent.broadcast.status == BroadcastStatus.SENDING
    assert len(adm.world.outbox) == 1


async def test_time_without_a_zone_is_refused(adm: Admin) -> None:
    """ADM-11: scheduled times are unambiguous."""
    view = await adm.draft()

    with pytest.raises(BroadcastTimeInvalidError):
        await adm.send.execute(
            adm.actor, view.broadcast.id, adm.clock.now().replace(tzinfo=None)
        )


async def test_sending_to_nobody_is_refused_and_the_draft_stays_a_draft(
    adm: Admin,
) -> None:
    """ADM-11: an empty audience cannot be sent."""
    view = await adm.draft(Audience(roles=[Role.LMS_ADMIN]))

    with pytest.raises(BroadcastEmptyAudienceError):
        await adm.send.execute(adm.actor, view.broadcast.id)

    assert adm.status(view.broadcast.id) == BroadcastStatus.DRAFT


async def test_a_broadcast_is_sent_only_once(adm: Admin) -> None:
    """ADM-11: sending twice is a conflict, not a second delivery."""
    adm.students(1)
    view = await adm.draft()
    await adm.send.execute(adm.actor, view.broadcast.id)

    with pytest.raises(BroadcastNotSendableError):
        await adm.send.execute(adm.actor, view.broadcast.id)

    assert len(adm.world.outbox) == 1


# - - - Preview and cancel - - -


async def test_preview_goes_only_to_the_admin_and_is_not_counted(adm: Admin) -> None:
    """UF-ADM-08 step 3: preview to my own Telegram."""
    adm.students(2)
    view = await adm.draft()

    await adm.preview.execute(adm.actor, view.broadcast.id)

    (draft,) = adm.world.outbox
    assert draft.user_id == adm.actor.user_id
    assert draft.broadcast_id is None
    assert draft.dedupe_key.startswith(f"bcp:{view.broadcast.id}:")
    assert draft.payload["preview"] is True
    assert adm.status(view.broadcast.id) == BroadcastStatus.DRAFT


async def test_preview_needs_a_linked_telegram_account(adm: Admin) -> None:
    """UF-ADM-08 step 3: without Telegram there is nothing to preview on."""
    adm.identity.accounts[adm.actor.user_id] = []
    view = await adm.draft()

    with pytest.raises(BroadcastNoTelegramError):
        await adm.preview.execute(adm.actor, view.broadcast.id)


async def test_scheduled_broadcast_can_be_cancelled_a_draft_cannot(
    adm: Admin,
) -> None:
    """UF-ADM-08 alternative 4a: cancel until it starts."""
    adm.students(1)
    scheduled = await adm.draft()
    await adm.send.execute(
        adm.actor, scheduled.broadcast.id, adm.clock.now() + timedelta(hours=1)
    )
    plain = await adm.draft()

    cancelled = await adm.cancel.execute(adm.actor, scheduled.broadcast.id)
    with pytest.raises(BroadcastNotCancellableError):
        await adm.cancel.execute(adm.actor, plain.broadcast.id)

    assert cancelled.broadcast.status == BroadcastStatus.CANCELLED
    with pytest.raises(BroadcastNotSendableError):
        await adm.send.execute(adm.actor, scheduled.broadcast.id)


# - - - Scheduler tasks - - -


async def test_scheduled_broadcast_starts_at_its_time(adm: Admin) -> None:
    """UF-ADM-08 4a: the minute task starts it when the time comes."""
    students = adm.students(2)
    view = await adm.draft()
    bid = view.broadcast.id
    await adm.send.execute(adm.actor, bid, adm.clock.now() + timedelta(minutes=30))

    early = await adm.start_scheduled.execute()
    adm.clock.advance(minutes=30)
    started = await adm.start_scheduled.execute()
    again = await adm.start_scheduled.execute()

    assert (early, started, again) == (0, 1, 0)
    assert adm.status(bid) == BroadcastStatus.SENDING
    assert {d.user_id for d in adm.world.outbox} == {s.id for s in students}
    assert [a.type for a in adm.world.audits] == ["broadcast.sent"]


async def test_scheduled_broadcast_with_nobody_left_finishes_empty(adm: Admin) -> None:
    """The audience can shrink while the broadcast waits."""
    (student,) = adm.students(1)
    view = await adm.draft()
    await adm.send.execute(
        adm.actor, view.broadcast.id, adm.clock.now() + timedelta(minutes=5)
    )
    adm.identity.users.pop(student.id)
    adm.clock.advance(minutes=5)

    started = await adm.start_scheduled.execute()

    assert started == 0
    assert adm.status(view.broadcast.id) == BroadcastStatus.SENT
    assert adm.world.outbox == []


async def test_broadcast_finishes_when_nothing_is_open_and_stats_are_frozen(
    adm: Admin,
) -> None:
    """BOT-22, ADM-11: sent / failed / blocked counts are stored on the broadcast."""
    adm.students(10)
    view = await adm.draft()
    bid = view.broadcast.id
    await adm.send.execute(adm.actor, bid)

    adm.world.deliveries.set(bid, total=10, sent=6, open=4)
    assert await adm.finish.execute() == 0
    live = await adm.get.execute(adm.actor, bid)
    assert live.stats is not None and (live.stats.total, live.stats.sent) == (10, 6)

    adm.world.deliveries.set(bid, total=10, sent=7, failed=1, blocked=2, open=0)
    assert await adm.finish.execute() == 1

    done = await adm.get.execute(adm.actor, bid)
    assert done.broadcast.status == BroadcastStatus.SENT
    assert done.stats is not None
    assert (done.stats.total, done.stats.sent) == (10, 7)
    assert (done.stats.failed, done.stats.blocked) == (1, 2)

    adm.world.deliveries.set(bid, total=10, sent=0, failed=10)
    done_again = await adm.get.execute(adm.actor, bid)
    assert done_again.stats is not None and done_again.stats.sent == 7  # frozen


async def test_interrupted_delivery_is_resumed_before_the_broadcast_finishes(
    adm: Admin,
) -> None:
    """Fewer notifications than recipients: the missing ones are written again."""
    adm.students(5)
    view = await adm.draft()
    bid = view.broadcast.id
    await adm.send.execute(adm.actor, bid)
    adm.world.outbox.clear()
    adm.world.deliveries.set(bid, total=2, sent=2)

    finished = await adm.finish.execute()

    assert finished == 0
    assert adm.status(bid) == BroadcastStatus.SENDING
    assert len(adm.world.outbox) == 5  # idempotent: dedupe keys drop the 2 existing


# - - - Listing - - -


async def test_list_filters_by_status_and_pages_newest_first(adm: Admin) -> None:
    """ADM-11: the broadcasts page lists drafts, scheduled and sent."""
    adm.students(1)
    first = await adm.draft()
    adm.clock.advance(minutes=1)
    second = await adm.draft()
    adm.clock.advance(minutes=1)
    third = await adm.draft()
    await adm.send.execute(
        adm.actor, third.broadcast.id, adm.clock.now() + timedelta(hours=1)
    )

    page_one = await adm.list.execute(adm.actor, limit=2)
    page_two = await adm.list.execute(adm.actor, cursor=page_one.next_cursor, limit=2)
    drafts = await adm.list.execute(adm.actor, status=BroadcastStatus.DRAFT)

    ids = [v.broadcast.id for v in page_one.items + page_two.items]
    assert ids == [third.broadcast.id, second.broadcast.id, first.broadcast.id]
    assert page_two.next_cursor is None
    assert [v.broadcast.id for v in drafts.items] == [
        second.broadcast.id,
        first.broadcast.id,
    ]
