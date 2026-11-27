"""Event, ReminderPlanner, Rsvp/waitlist, Rating (spec 4.3, 4.6).

The implementation must provide, under `app.modules.activities.domain`:
  event: EventStatus (draft|scheduled|cancelled|done), RsvpPolicy
  (open|members|approval),
    Event(id, club_id, title, starts_at, ends_at, capacity, rsvp_policy, status, ...)
    .validate() (ends_at > starts_at else EventInvalidError; tz-aware),
    .schedule(), .cancel(), .reschedule(starts_at, ends_at) -> bool (True if the time
    changed),
    .mark_done(); EventStateError
    Event.schedule_revision: int (default 0), +1 on every reschedule that changes the
    time.
    CHECK_IN_OPENS_BEFORE == 1h, CHECK_IN_CLOSES_AFTER == 1h; check_in_window(event) ->
    (opens, closes);
    CheckInWindowError outside it.
    Rsvp.request(event, user_id, going_count, is_member) -> status
    going|waitlist|requested
    ('open': going until capacity then waitlist; 'approval' -> status 'requested'
    waiting for
    organizers; 'members' -> NotMemberError for non-members); promote_waitlist(rsvps) ->
    Rsvp|None
    (first by created order); check_in(rsvp, method 'qr'|'manual', now, *, event) (must
    be going and inside
    the window; cancelled/draft/done events: EventStateError; outside:
    CheckInWindowError)
  checkin_token: issue_token(event, secret, now) -> str, verify_token(token, event_id,
  secret, now) -> UUID
    (HMAC-signed, event-bound, expires at the window close; InvalidCheckInTokenError
    when tampered, expired
    or for another event)
  reminders: REMINDER_OFFSETS == (60, 15, 5); reminder_prefix(event_id) ->
  'activities:event:{id}:';
    dedupe_key(event_id, revision, offset, user_id) ->
    'activities:event:{id}:r{revision}:{offset}:{user}'
    (the revision keeps a post-reschedule reminder from colliding with an already sent
    one);
    plan_reminders(event, participants, organizers, now) -> list[NotificationDraft]
      (type NotificationType.EVENT_REMINDER; payload has event_id, offset, role
      'participant'|'organizer',
       organizers also get 'headcount' and 'check_in_link'; offsets already in the past
       are skipped;
       a user who is both participant and organizer gets organizer reminders only, one
       per offset;
       only scheduled events plan; cancelled/draft -> [])
    rating_request_time(event) -> ends_at + 2h
  rating: Rating(target_type event|club, ...); rate_event(event, attendee_checked_in,
  now, score,...),
    rate_club(membership, now, existing_this_term) enforcing the spec windows;
    RatingInvalidError,
    RatingNotAllowedError; MAX_COMMENT == 1000; aggregates(ratings) -> {count, avg,
    aspects{..}};
    owner_view(rating) for an anonymous_to_club rating contains NO author key at all (no
    user_id, name,
    photo) while the comment text stays; reveal_author(rating, *, by_user, roles,
    reason) -> RevealAudit is
    ADMIN/ACTIVITIES_ADMIN only (SU and club owners: PermissionDeniedError), reason
    required (ValueError)
  app.shared.notifications.NotificationType gains EVENT_REMINDER, EVENT_CHANGED,
  EVENT_CANCELLED,
    EVENT_RATING_REQUEST, CLUB_ANNOUNCEMENT, CLUB_JOIN_REQUEST, CLUB_JOIN_RESULT,
    CLUB_TRANSFER_OFFER, DRAFT_INVITE, POSITION_APPLICATION_RESULT
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.checkin_token import (
    InvalidCheckInTokenError,
    issue_token,
    verify_token,
)
from app.modules.activities.domain.event import (
    CheckInWindowError,
    Event,
    EventInvalidError,
    EventStateError,
    EventStatus,
    NotMemberError,
    Rsvp,
    RsvpPolicy,
    check_in,
    check_in_window,
    promote_waitlist,
)
from app.modules.activities.domain.rating import (
    MAX_COMMENT,
    Rating,
    RatingInvalidError,
    RatingNotAllowedError,
    aggregates,
    owner_view,
    rate_club,
    rate_event,
    reveal_author,
)
from app.modules.activities.domain.reminders import (
    REMINDER_OFFSETS,
    dedupe_key,
    plan_reminders,
    rating_request_time,
    reminder_prefix,
)
from app.shared.actor import Role
from app.shared.notifications import NotificationType

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)
START = NOW + timedelta(hours=3)


def event(**kw: object) -> Event:
    base: dict[str, object] = {
        "id": uuid4(),
        "club_id": uuid4(),
        "title": {"en": "Quiz"},
        "starts_at": START,
        "ends_at": START + timedelta(hours=2),
        "capacity": 2,
        "rsvp_policy": RsvpPolicy.OPEN,
        "status": EventStatus.SCHEDULED,
    }
    base.update(kw)
    return Event(**base)  # type: ignore[arg-type]


def test_end_must_follow_start_and_be_timezone_aware() -> None:
    with pytest.raises(EventInvalidError):
        event(ends_at=START).validate()
    with pytest.raises(EventInvalidError):
        event(ends_at=START - timedelta(minutes=1)).validate()
    with pytest.raises(EventInvalidError):
        event(starts_at=datetime(2026, 12, 1, 10)).validate()
    event().validate()


def test_event_state_machine() -> None:
    e = event(status=EventStatus.DRAFT)
    e.schedule()
    assert e.status == EventStatus.SCHEDULED
    e.cancel()
    assert e.status == EventStatus.CANCELLED
    with pytest.raises(EventStateError):
        e.schedule()
    with pytest.raises(EventStateError):
        e.reschedule(START, START + timedelta(hours=1))


def test_reschedule_reports_whether_the_time_changed() -> None:
    e = event()
    assert e.reschedule(START, e.ends_at) is False
    assert (
        e.reschedule(START + timedelta(days=1), START + timedelta(days=1, hours=1))
        is True
    )
    with pytest.raises(EventInvalidError):
        e.reschedule(START, START)


# ---- rsvp ---------------------------------------------------------------------


def test_open_rsvp_goes_until_capacity_then_waitlist() -> None:
    e = event(capacity=2)
    assert Rsvp.request(e, uuid4(), going_count=1, is_member=False).status == "going"
    assert Rsvp.request(e, uuid4(), going_count=2, is_member=False).status == "waitlist"


def test_unlimited_capacity() -> None:
    assert (
        Rsvp.request(
            event(capacity=None), uuid4(), going_count=999, is_member=False
        ).status
        == "going"
    )


def test_members_only_events_refuse_outsiders() -> None:
    e = event(rsvp_policy=RsvpPolicy.MEMBERS)
    with pytest.raises(NotMemberError):
        Rsvp.request(e, uuid4(), 0, is_member=False)
    assert Rsvp.request(e, uuid4(), 0, is_member=True).status == "going"


def test_approval_events_wait_for_an_organizer() -> None:
    assert (
        Rsvp.request(event(rsvp_policy=RsvpPolicy.APPROVAL), uuid4(), 0, False).status
        == "requested"
    )


def test_cancelled_events_take_no_rsvps() -> None:
    with pytest.raises(EventStateError):
        Rsvp.request(event(status=EventStatus.CANCELLED), uuid4(), 0, True)


def test_waitlist_promotes_the_oldest_first() -> None:
    e = event()
    first = Rsvp.request(e, uuid4(), 2, False)
    first.created_at = NOW
    second = Rsvp.request(e, uuid4(), 2, False)
    second.created_at = NOW + timedelta(minutes=1)
    promoted = promote_waitlist([second, first])
    assert promoted is first and first.status == "going" and second.status == "waitlist"
    assert promote_waitlist([]) is None


def test_check_in_needs_a_going_rsvp() -> None:
    e = event()
    at = START - timedelta(minutes=10)
    r = Rsvp.request(e, uuid4(), 0, False)
    check_in(r, "qr", at, event=e)
    assert (r.checked_in_at, r.check_in_method) == (at, "qr")
    w = Rsvp.request(e, uuid4(), 5, False)
    with pytest.raises(EventStateError):
        check_in(w, "manual", at, event=e)
    with pytest.raises(ValueError):
        check_in(r, "telepathy", at, event=e)


def test_check_in_window_is_one_hour_before_to_one_hour_after() -> None:
    e = event()
    assert check_in_window(e) == (
        START - timedelta(hours=1),
        e.ends_at + timedelta(hours=1),
    )
    for bad in (
        START - timedelta(hours=1, seconds=1),
        e.ends_at + timedelta(hours=1, seconds=1),
        NOW,
    ):
        with pytest.raises(CheckInWindowError):
            check_in(Rsvp.request(e, uuid4(), 0, False), "manual", bad, event=e)
    check_in(
        Rsvp.request(e, uuid4(), 0, False),
        "manual",
        START - timedelta(hours=1),
        event=e,
    )
    check_in(
        Rsvp.request(e, uuid4(), 0, False),
        "manual",
        e.ends_at + timedelta(hours=1),
        event=e,
    )


@pytest.mark.parametrize("status", [EventStatus.DRAFT, EventStatus.CANCELLED])
def test_no_check_in_for_unpublished_or_cancelled_events(status: EventStatus) -> None:
    e = event()
    r = Rsvp.request(e, uuid4(), 0, False)
    e.status = status
    with pytest.raises(EventStateError):
        check_in(r, "manual", START, event=e)


def test_check_in_window_follows_a_reschedule() -> None:
    e = event()
    e.reschedule(START + timedelta(days=1), START + timedelta(days=1, hours=2))
    with pytest.raises(CheckInWindowError):
        check_in(Rsvp.request(e, uuid4(), 0, False), "manual", START, event=e)


def test_qr_token_is_signed_bound_and_expires() -> None:
    e = event()
    at = START - timedelta(minutes=5)
    tok = issue_token(e, "secret", at)
    assert verify_token(tok, e.id, "secret", at) == e.id
    with pytest.raises(InvalidCheckInTokenError):
        verify_token(
            tok[:-2] + ("aa" if not tok.endswith("aa") else "bb"), e.id, "secret", at
        )
    with pytest.raises(InvalidCheckInTokenError):
        verify_token(tok, e.id, "other-secret", at)
    with pytest.raises(InvalidCheckInTokenError):
        verify_token(tok, uuid4(), "secret", at)  # bound to the event
    with pytest.raises(InvalidCheckInTokenError):
        verify_token(tok, e.id, "secret", e.ends_at + timedelta(hours=1, seconds=1))


# ---- reminders ----------------------------------------------------------------


def test_offsets_and_keys() -> None:
    assert REMINDER_OFFSETS == (60, 15, 5)
    eid, uid = uuid4(), uuid4()
    assert reminder_prefix(eid) == f"activities:event:{eid}:"
    assert dedupe_key(eid, 0, 15, uid) == f"activities:event:{eid}:r0:15:{uid}"
    assert dedupe_key(eid, 1, 15, uid) != dedupe_key(eid, 0, 15, uid)
    assert dedupe_key(eid, 0, 15, uid).startswith(reminder_prefix(eid))


def test_every_participant_and_organizer_gets_three_reminders() -> None:
    e = event()
    parts, orgs = [uuid4(), uuid4()], [uuid4()]
    drafts = plan_reminders(e, parts, orgs, NOW)
    assert len(drafts) == 9
    assert {d.type for d in drafts} == {NotificationType.EVENT_REMINDER}
    by_user: dict = {}
    for d in drafts:
        by_user.setdefault(d.user_id, []).append(d)
    assert set(by_user) == {*parts, *orgs}
    for d in drafts:
        assert d.scheduled_at == e.starts_at - timedelta(minutes=d.payload["offset"])
        assert d.dedupe_key == dedupe_key(
            e.id, e.schedule_revision, d.payload["offset"], d.user_id
        )
    assert {d.payload["offset"] for d in drafts} == {60, 15, 5}


def test_dedupe_keys_are_unique() -> None:
    drafts = plan_reminders(event(), [uuid4()], [uuid4()], NOW)
    assert len({d.dedupe_key for d in drafts}) == len(drafts)


def test_organizer_reminders_carry_check_in_link_and_headcount() -> None:
    org, part = uuid4(), uuid4()
    drafts = plan_reminders(event(), [part], [org], NOW)
    o = [d for d in drafts if d.user_id == org]
    p = [d for d in drafts if d.user_id == part]
    assert all(
        d.payload["role"] == "organizer"
        and "check_in_link" in d.payload
        and d.payload["headcount"] == 1
        for d in o
    )
    assert all(
        d.payload["role"] == "participant" and "check_in_link" not in d.payload
        for d in p
    )


def test_a_person_in_both_lists_gets_only_organizer_reminders() -> None:
    both = uuid4()
    drafts = plan_reminders(event(), [both], [both], NOW)
    assert len(drafts) == 3 and {d.payload["role"] for d in drafts} == {"organizer"}


def test_past_offsets_are_skipped() -> None:
    e = event(starts_at=NOW + timedelta(minutes=20), ends_at=NOW + timedelta(hours=1))
    offsets = {d.payload["offset"] for d in plan_reminders(e, [uuid4()], [], NOW)}
    assert offsets == {15, 5}
    soon = event(starts_at=NOW + timedelta(minutes=2), ends_at=NOW + timedelta(hours=1))
    assert plan_reminders(soon, [uuid4()], [], NOW) == []


@pytest.mark.parametrize(
    "status", [EventStatus.DRAFT, EventStatus.CANCELLED, EventStatus.DONE]
)
def test_only_scheduled_events_plan_reminders(status: EventStatus) -> None:
    assert plan_reminders(event(status=status), [uuid4()], [uuid4()], NOW) == []


def test_replanning_after_a_time_change_bumps_the_revision_so_no_key_repeats() -> None:
    """Reschedule = cancel_scheduled(prefix) (pending/claimed rows only; sent history
    stays), then plan
    again. New keys live under the prefix but never equal an old key, even for the same
    user and offset, so
    notify's ON CONFLICT DO NOTHING cannot swallow the new reminder after an earlier one
    was sent.
    """
    e = event()
    user = uuid4()
    before = plan_reminders(e, [user], [], NOW)
    assert e.schedule_revision == 0
    assert (
        e.reschedule(START + timedelta(days=1), START + timedelta(days=1, hours=1))
        is True
    )
    assert e.schedule_revision == 1
    after = plan_reminders(e, [user], [], NOW)
    assert all(d.dedupe_key.startswith(reminder_prefix(e.id)) for d in before + after)
    assert {d.dedupe_key for d in before}.isdisjoint({d.dedupe_key for d in after})
    assert {d.scheduled_at for d in after}.isdisjoint({d.scheduled_at for d in before})
    same = event()
    assert (
        same.reschedule(same.starts_at, same.ends_at) is False
        and same.schedule_revision == 0
    )


def test_rating_request_is_two_hours_after_the_end() -> None:
    e = event()
    assert rating_request_time(e) == e.ends_at + timedelta(hours=2)


# ---- ratings ------------------------------------------------------------------


ASPECTS = {"organization": 5, "usefulness": 4, "atmosphere": 4}


def test_event_rating_needs_check_in_and_the_14_day_window() -> None:
    e = event()
    after_end = e.ends_at + timedelta(hours=1)
    r = rate_event(
        e, checked_in=True, now=after_end, user_id=uuid4(), score=5, aspects=ASPECTS
    )
    assert r.target_type == "event" and r.target_id == e.id
    with pytest.raises(RatingNotAllowedError):
        rate_event(
            e,
            checked_in=False,
            now=after_end,
            user_id=uuid4(),
            score=5,
            aspects=ASPECTS,
        )
    with pytest.raises(RatingNotAllowedError):  # before it ended
        rate_event(
            e,
            checked_in=True,
            now=e.starts_at,
            user_id=uuid4(),
            score=5,
            aspects=ASPECTS,
        )
    with pytest.raises(RatingNotAllowedError):  # after 14 days
        rate_event(
            e,
            checked_in=True,
            now=e.ends_at + timedelta(days=14, seconds=1),
            user_id=uuid4(),
            score=5,
            aspects=ASPECTS,
        )
    rate_event(
        e,
        checked_in=True,
        now=e.ends_at + timedelta(days=14),
        user_id=uuid4(),
        score=3,
        aspects=ASPECTS,
    )


def test_club_rating_needs_30_days_membership_and_one_per_term() -> None:
    joined = NOW - timedelta(days=30)
    club_id = uuid4()
    rate_club(
        club_id,
        uuid4(),
        joined_at=joined,
        now=NOW,
        already_rated_this_term=False,
        score=4,
        aspects=ASPECTS,
    )
    with pytest.raises(RatingNotAllowedError):
        rate_club(
            club_id,
            uuid4(),
            joined_at=NOW - timedelta(days=29),
            now=NOW,
            already_rated_this_term=False,
            score=4,
            aspects=ASPECTS,
        )
    with pytest.raises(RatingNotAllowedError):
        rate_club(
            club_id,
            uuid4(),
            joined_at=joined,
            now=NOW,
            already_rated_this_term=True,
            score=4,
            aspects=ASPECTS,
        )


@pytest.mark.parametrize("score", [0, 6, -1])
def test_score_is_1_to_5(score: int) -> None:
    with pytest.raises(RatingInvalidError):
        rate_event(
            event(),
            checked_in=True,
            now=event().ends_at + timedelta(hours=1),
            user_id=uuid4(),
            score=score,
            aspects=ASPECTS,
        )


def test_comment_is_capped() -> None:
    assert MAX_COMMENT == 1000
    e = event()
    with pytest.raises(RatingInvalidError):
        rate_event(
            e,
            checked_in=True,
            now=e.ends_at + timedelta(hours=1),
            user_id=uuid4(),
            score=4,
            aspects=ASPECTS,
            comment="x" * 1001,
        )


def test_unknown_aspects_are_rejected() -> None:
    e = event()
    with pytest.raises(RatingInvalidError):
        rate_event(
            e,
            checked_in=True,
            now=e.ends_at + timedelta(hours=1),
            user_id=uuid4(),
            score=4,
            aspects={"vibes": 5},
        )


def _rating(score: int, org: int, anon: bool = False) -> Rating:
    e = event()
    return rate_event(
        e,
        checked_in=True,
        now=e.ends_at + timedelta(hours=1),
        user_id=uuid4(),
        score=score,
        aspects={"organization": org},
        anonymous_to_club=anon,
    )


def test_aggregates_match_the_raw_data() -> None:
    rs = [_rating(5, 5), _rating(3, 1), _rating(4, 3)]
    agg = aggregates(rs)
    assert agg["count"] == 3
    assert agg["avg"] == pytest.approx(4.0)
    assert agg["aspects"]["organization"] == pytest.approx(3.0)
    assert aggregates([]) == {"count": 0, "avg": None, "aspects": {}}


def test_anonymous_ratings_hide_the_author_from_owners() -> None:
    e = event()
    r = rate_event(
        e,
        checked_in=True,
        now=e.ends_at + timedelta(hours=1),
        user_id=uuid4(),
        score=4,
        aspects={"organization": 4},
        comment="loved it",
        anonymous_to_club=True,
    )
    v = owner_view(r)
    assert v["comment"] == "loved it"  # non-empty: the leak check below is meaningful
    assert not {
        "user_id",
        "author",
        "name",
        "display_name",
        "photo_url",
        "avatar",
    } & set(v)
    assert str(r.user_id) not in str(v)
    named = _rating(4, 4, anon=False)
    assert owner_view(named)["user_id"] == named.user_id


def test_only_admin_roles_reveal_an_anonymous_author() -> None:
    e = event()
    r = rate_event(
        e,
        checked_in=True,
        now=e.ends_at + timedelta(hours=1),
        user_id=uuid4(),
        score=1,
        aspects={"organization": 1},
        comment="bad",
        anonymous_to_club=True,
    )
    me = uuid4()
    for roles in ({Role.SU}, {Role.STUDENT}, {Role.SU, Role.STUDENT}):
        with pytest.raises(PermissionDeniedError):
            reveal_author(r, by_user=me, roles=frozenset(roles), reason="complaint")
    with pytest.raises(ValueError):
        reveal_author(
            r, by_user=me, roles=frozenset({Role.ACTIVITIES_ADMIN}), reason=" "
        )
    audit = reveal_author(
        r, by_user=me, roles=frozenset({Role.ACTIVITIES_ADMIN}), reason="complaint"
    )
    assert (audit.rating_id, audit.revealed_user_id, audit.by_user) == (
        r.id,
        r.user_id,
        me,
    )
