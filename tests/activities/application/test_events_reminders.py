"""EventService, RatingService, AnnouncementService (spec 4.5, 4.6, phase 2 exit).

events.create(actor, club_id, title, starts_at, ends_at, capacity=None,
rsvp_policy='open')->Event;
  .publish(actor, event_id); .reschedule(actor, event_id, starts_at, ends_at);
  .cancel(actor, event_id);
  .rsvp(actor, event_id)->Rsvp; .cancel_rsvp(actor, event_id);
  .check_in(actor, event_id, user_id, "manual") (organizers only: PermissionDeniedError
  otherwise);
  .qr_token(organizer, event_id) -> str; .check_in_qr(actor, token) (self check-in by
  scanning: the token is
  an HMAC-signed, event-bound value valid only inside the check-in window;
  InvalidCheckInTokenError when
  tampered/expired/for an event the actor has no going RSVP for; method recorded as
  "qr"). Check-in is
  open from starts_at - 1h to ends_at + 1h (CheckInWindowError outside; cancelled event:
  EventStateError;
  a reschedule moves the window).
  .finish(actor, event_id); .assign_role(actor, event_id, user_id, role); .rate_due() ->
  int
  (sends rating requests at ends_at+2h)
ratings.rate_event(actor, event_id, score, aspects, comment=None,
anonymous_to_club=False);
  .rate_club(actor, club_id, ...); .summary(actor, club_id)
announcements.send(actor, club_id, text, audience, scheduled_at=None)->Announcement; NO
channel argument
  (delivery follows each recipient's preferences); audience:
  'members'|'team'|'event:<uuid>';
  .cancel(actor, ann_id); .list(actor, club_id)
Fake world: .deliver_due() marks scheduled rows with scheduled_at <= now as delivered; a
delivered or
  pending row keeps its dedupe_key reserved (insert with an existing key is silently
  dropped, exactly like
  notify's outbox ON CONFLICT DO NOTHING); .scheduled holds pending rows only,
  .delivered the sent ones.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.announcement import AnnouncementLimitError
from app.modules.activities.domain.checkin_token import InvalidCheckInTokenError
from app.modules.activities.domain.club import Club
from app.modules.activities.domain.event import (
    CheckInWindowError,
    Event,
    EventStateError,
)
from app.modules.activities.domain.rating import RatingNotAllowedError
from app.modules.activities.domain.reminders import reminder_prefix
from app.shared.actor import Actor
from app.shared.notifications import NotificationType
from tests.fakes.activities.world import ActivitiesWorld

import pytest


async def _event(
    world: ActivitiesWorld,
    club: Club,
    owner: Actor,
    hours: int = 3,
    capacity: int | None = None,
) -> Any:
    now = world.clock.now()
    e = await world.services.events.create(
        owner,
        club.id,
        title={"en": "Quiz"},
        starts_at=now + timedelta(hours=hours),
        ends_at=now + timedelta(hours=hours + 2),
        capacity=capacity,
        rsvp_policy="open",
    )
    await world.services.events.publish(owner, e.id)
    return e


def _open_check_in(world: ActivitiesWorld, e: Event) -> None:
    world.clock.set(e.starts_at - timedelta(minutes=10))


def _reminders(world: ActivitiesWorld, eid: UUID) -> Any:
    return [n for n in world.scheduled if n.dedupe_key.startswith(reminder_prefix(eid))]


async def test_rsvp_writes_three_reminders_per_participant(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    mine = [n for n in _reminders(world, e.id) if n.user_id == student.user_id]
    assert sorted(n.payload["offset"] for n in mine) == [5, 15, 60]
    assert all(n.type == NotificationType.EVENT_REMINDER for n in mine)


async def test_organizers_get_reminders_too(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    e = await _event(world, club, owner)
    mine = [n for n in _reminders(world, e.id) if n.user_id == owner.user_id]
    assert len(mine) == 3 and all("check_in_link" in n.payload for n in mine)


async def test_double_rsvp_does_not_duplicate_reminders(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    try:
        await world.services.events.rsvp(student, e.id)
    except Exception:
        pass
    keys = [n.dedupe_key for n in _reminders(world, e.id)]
    assert len(keys) == len(set(keys))


async def test_reschedule_after_a_reminder_was_sent_plans_fresh_reminders(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    """A sent 60-minute reminder must not block the new schedule's 60-minute reminder
    (identity carries the
    schedule revision), and the sent history stays; pending/claimed rows of the old
    schedule are dropped.
    """
    e = await _event(world, club, owner, hours=5)
    await world.services.events.rsvp(student, e.id)
    world.clock.set(e.starts_at - timedelta(minutes=59))
    world.deliver_due()
    sent_keys = {n.dedupe_key for n in world.delivered if n.user_id == student.user_id}
    assert len(sent_keys) == 1  # the 60-minute one
    await world.services.events.reschedule(
        owner, e.id, e.starts_at + timedelta(days=1), e.ends_at + timedelta(days=1)
    )
    mine = [n for n in _reminders(world, e.id) if n.user_id == student.user_id]
    assert sorted(n.payload["offset"] for n in mine) == [
        5,
        15,
        60,
    ]  # fresh trio, incl. the 60 again
    assert sent_keys.isdisjoint({n.dedupe_key for n in mine})
    assert sent_keys <= {n.dedupe_key for n in world.delivered}  # history kept
    assert all(n.scheduled_at > world.clock.now() for n in mine)


async def test_reschedule_replaces_reminders_and_notifies(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    before = {n.scheduled_at for n in _reminders(world, e.id)}
    await world.services.events.reschedule(
        owner, e.id, e.starts_at + timedelta(days=1), e.ends_at + timedelta(days=1)
    )
    after = {n.scheduled_at for n in _reminders(world, e.id)}
    assert after and before.isdisjoint(after)
    assert any(
        n.type == NotificationType.EVENT_CHANGED and n.user_id == student.user_id
        for n in world.sent
    )


async def test_cancel_notifies_rsvps_and_removes_pending_reminders(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    await world.services.events.cancel(owner, e.id)
    assert _reminders(world, e.id) == []
    assert any(
        n.type == NotificationType.EVENT_CANCELLED and n.user_id == student.user_id
        for n in world.sent
    )


async def test_cancel_rsvp_removes_that_users_reminders(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    await world.services.events.cancel_rsvp(student, e.id)
    assert [n for n in _reminders(world, e.id) if n.user_id == student.user_id] == []


async def test_waitlist_promotion_when_a_going_user_leaves(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    e = await _event(world, club, owner, capacity=1)
    a, b = world.add_student(), world.add_student()
    assert (await world.services.events.rsvp(a, e.id)).status == "going"
    assert (await world.services.events.rsvp(b, e.id)).status == "waitlist"
    await world.services.events.cancel_rsvp(a, e.id)
    mine = [n for n in _reminders(world, e.id) if n.user_id == b.user_id]
    assert len(mine) == 3  # promoted user now gets reminders


async def test_only_organizers_manage_events(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    now = world.clock.now()
    with pytest.raises(PermissionDeniedError):
        await world.services.events.create(
            student,
            club.id,
            title={"en": "x"},
            starts_at=now + timedelta(hours=3),
            ends_at=now + timedelta(hours=4),
        )


async def test_rating_request_fires_two_hours_after_the_end(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    _open_check_in(world, e)
    await world.services.events.check_in(owner, e.id, student.user_id, "manual")
    world.clock.set(e.ends_at + timedelta(hours=1, minutes=59))
    assert await world.services.events.rate_due() == 0
    world.clock.set(e.ends_at + timedelta(hours=2, minutes=1))
    assert await world.services.events.rate_due() == 1
    assert any(
        n.type == NotificationType.EVENT_RATING_REQUEST and n.user_id == student.user_id
        for n in world.sent
    )
    assert await world.services.events.rate_due() == 0  # idempotent


async def test_only_checked_in_attendees_rate(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    world.clock.set(e.ends_at + timedelta(hours=3))
    with pytest.raises(RatingNotAllowedError):
        await world.services.ratings.rate_event(student, e.id, 5, {"organization": 5})


async def test_check_in_then_rate_and_summary(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    _open_check_in(world, e)
    await world.services.events.check_in(owner, e.id, student.user_id, "manual")
    world.clock.set(e.ends_at + timedelta(hours=3))
    await world.services.ratings.rate_event(
        student, e.id, 4, {"organization": 4}, comment="nice", anonymous_to_club=True
    )
    s = await world.services.ratings.summary(owner, club.id)
    assert s["events"]["count"] == 1 and s["events"]["avg"] == 4
    assert [c["comment"] for c in s["comments"]] == [
        "nice"
    ]  # the comment IS shown, so the checks below bite
    for c in s["comments"]:
        assert not {
            "user_id",
            "author",
            "name",
            "display_name",
            "photo_url",
            "avatar",
        } & set(c)
    blob = str(s)
    assert str(student.user_id) not in blob and world.name_of(student) not in blob


async def test_anonymous_author_is_staff_only_audited_and_not_a_role_union(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor, su: Actor
) -> None:
    """SU and club owner (even one student holding both) never see the author; only
    ADMIN/ACTIVITIES_ADMIN
    reveal it through an audited call that needs a reason."""
    from app.modules.activities.domain.access import PermissionDeniedError as Denied
    from app.shared.actor import Role

    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    _open_check_in(world, e)
    await world.services.events.check_in(owner, e.id, student.user_id, "manual")
    world.clock.set(e.ends_at + timedelta(hours=3))
    r = await world.services.ratings.rate_event(
        student, e.id, 2, {"organization": 2}, comment="boring", anonymous_to_club=True
    )
    dual = world.add_staff(
        Role.SU
    )  # global SU who is also the club owner would still be denied
    for who in (owner, su, dual):
        with pytest.raises(Denied):
            await world.services.ratings.reveal_author(who, r.id, reason="complaint")
    admin = world.add_staff(Role.ACTIVITIES_ADMIN)
    with pytest.raises(ValueError):
        await world.services.ratings.reveal_author(admin, r.id, reason="")
    got = await world.services.ratings.reveal_author(admin, r.id, reason="complaint")
    assert got.user_id == student.user_id
    assert [
        a.actor_id for a in world.audit if a.action == "activities.rating.reveal_author"
    ] == [admin.user_id]


async def test_qr_check_in_token(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    other = await _event(world, club, owner, hours=6)
    await world.services.events.rsvp(student, e.id)
    token = await world.services.events.qr_token(owner, e.id)
    _open_check_in(world, e)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(InvalidCheckInTokenError):
        await world.services.events.check_in_qr(student, tampered)
    with pytest.raises(
        InvalidCheckInTokenError
    ):  # a token of another event: student has no RSVP there
        await world.services.events.check_in_qr(
            student, await world.services.events.qr_token(owner, other.id)
        )
    with pytest.raises(PermissionDeniedError):  # students cannot mint tokens
        await world.services.events.qr_token(student, e.id)
    await world.services.events.check_in_qr(student, token)
    rsvps = await world.services.events.list_rsvps(owner, e.id)
    assert [(r.user_id, r.check_in_method) for r in rsvps if r.checked_in_at] == [
        (student.user_id, "qr")
    ]


async def test_qr_token_expires_with_the_window(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    token = await world.services.events.qr_token(owner, e.id)
    world.clock.set(e.ends_at + timedelta(hours=1, minutes=1))
    with pytest.raises(InvalidCheckInTokenError):
        await world.services.events.check_in_qr(student, token)


async def test_cancelled_event_takes_no_check_in(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    await world.services.events.cancel(owner, e.id)
    _open_check_in(world, e)
    with pytest.raises(EventStateError):
        await world.services.events.check_in(owner, e.id, student.user_id, "manual")


async def test_reschedule_moves_the_check_in_window(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    await world.services.events.reschedule(
        owner, e.id, e.starts_at + timedelta(days=1), e.ends_at + timedelta(days=1)
    )
    _open_check_in(world, e)  # the OLD window: now closed
    with pytest.raises(CheckInWindowError):
        await world.services.events.check_in(owner, e.id, student.user_id, "manual")
    world.clock.set(e.starts_at + timedelta(days=1) - timedelta(minutes=10))
    await world.services.events.check_in(owner, e.id, student.user_id, "manual")


async def test_announcement_cap_three_per_day(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    for _ in range(3):
        await world.services.announcements.send(owner, club.id, "hi", "members")
    with pytest.raises(AnnouncementLimitError):
        await world.services.announcements.send(owner, club.id, "hi", "members")
    await world.services.announcements.send(
        su, club.id, "hi", "members"
    )  # platform staff exempt
    world.clock.advance(hours=24)
    await world.services.announcements.send(owner, club.id, "hi", "members")


async def test_announcement_notifies_members_without_a_channel(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    import inspect

    assert not {"channel", "channels"} & set(
        inspect.signature(world.services.announcements.send).parameters
    )
    await world.services.memberships.join(student, club.id)
    await world.services.memberships.approve(owner, club.id, student.user_id)
    await world.services.announcements.send(
        owner, club.id, "<b>hi</b><script>x</script>", "members"
    )
    got = [n for n in world.sent if n.type == NotificationType.CLUB_ANNOUNCEMENT]
    assert student.user_id in {n.user_id for n in got}
    assert all("<script" not in str(n.payload) for n in got)
    assert all(
        not {"channel", "channels"} & (set(vars(n)) | set(n.payload)) for n in got
    )  # system decides


async def test_non_organizer_cannot_announce(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    with pytest.raises(PermissionDeniedError):
        await world.services.announcements.send(student, club.id, "hi", "members")
