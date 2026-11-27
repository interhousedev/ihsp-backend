"""Club volunteering services, points leaderboard, analytics, public clubs (spec 4.5,
4.10, 4.14).

Volunteers is a Club; drafting, forms, points and roster are `Club.capabilities` that
only SU toggles
(clubs.set_capabilities(su, club_id, caps)). Required service surface (all club-scoped,
capability-guarded):
  clubs.set_capabilities(actor, club_id, caps: set[ClubCapability]) -> Club (SU only;
  PermissionDeniedError
    otherwise; `drafting` implies `forms`)
  drafts.open_round(actor, event_id, club_id, needed); .signup(actor, round_id, role,
  answers);
    .rank(actor, round_id)->list[Ranked]; .pick(actor, round_id, user_id, role);
    .invite(actor, pick_id);
    .respond(actor, pick_id, accept); .complete(actor, pick_id);
    .mark_no_show_due()->int
    (accepted picks of finished events who were not checked in; runs only at ends_at +
    2h, the check-in
    window closes at ends_at + 1h, grace in between; writes -4 once). Needs `drafting`
    (CapabilityDisabledError when off); signup only for club members
    (NotClubMemberError).
  forms.save_profile(actor, club_id, answers) needs `forms` AND an active (not
  left/removed/banned)
    membership of that club (NotClubMemberError otherwise). Policy: forms/drafting serve
    members only;
    outsiders apply through team positions, never through drafts. Drafting also
    validates the event<->club
    pairing (open_round with another club's event -> DraftInvalidError), requires the
    actor to be an
    organizer of THAT club (PermissionDeniedError), re-checks the capability on
    signup/pick (revoked after a
    round opened -> CapabilityDisabledError), and refuses banned/removed signups.
  clubs memberships: memberships.join(actor, club_id); .members(actor, club_id)
  leaderboard.top(actor, club_id, term=None, limit=20)->rows; .my_points(actor,
  club_id); .set_opt_out(actor, bool);
    both need `points`; attendance/shift stats (leaderboard.attendance(actor, club_id))
    need `roster`.
  analytics.overview(su, since, until);
  public.list_clubs()/get_club(slug)/submit_contact(...) as before.
"""

from collections.abc import Collection
from datetime import timedelta
from typing import Any

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.club import (
    CapabilityDisabledError,
    Club,
    ClubCapability,
)
from app.modules.activities.domain.contact import (
    CaptchaFailedError,
    ContactNotAcceptedError,
    ContactUnavailableError,
)
from app.modules.activities.domain.draft import DraftInvalidError, NotClubMemberError
from app.modules.activities.domain.event import CheckInWindowError
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError, RateLimitedError
from app.shared.notifications import NotificationType
from tests.fakes.activities.world import ActivitiesWorld

import pytest


async def _done_event(world: ActivitiesWorld, club: Club, owner: Actor) -> Any:
    now = world.clock.now()
    e = await world.services.events.create(
        owner,
        club.id,
        title={"en": "Fest"},
        starts_at=now + timedelta(hours=3),
        ends_at=now + timedelta(hours=5),
    )
    await world.services.events.publish(owner, e.id)
    return e


ALL = {
    ClubCapability.FORMS,
    ClubCapability.DRAFTING,
    ClubCapability.POINTS,
    ClubCapability.ROSTER,
}


async def _volunteers(
    world: ActivitiesWorld,
    owner: Actor,
    su: Actor,
    caps: Collection[ClubCapability] = ALL,
) -> Any:
    """An active club "IHT Volunteers" with the given capabilities (SU only grants
    them)."""
    c = await world.services.clubs.create(
        owner, name="IHT Volunteers", slug="volunteers", description="d"
    )
    await world.services.clubs.submit(owner, c.id)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    return await world.services.clubs.set_capabilities(su, c.id, set(caps))


async def test_only_su_grants_capabilities(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    with pytest.raises(PermissionDeniedError):
        await world.services.clubs.set_capabilities(
            owner, club.id, {ClubCapability.POINTS}
        )
    c = await world.services.clubs.set_capabilities(
        su, club.id, {ClubCapability.DRAFTING}
    )
    assert c.capabilities == {ClubCapability.DRAFTING, ClubCapability.FORMS}


async def test_drafting_needs_the_capability(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    e = await _done_event(world, club, owner)
    with pytest.raises(CapabilityDisabledError):
        await world.services.drafts.open_round(owner, e.id, club.id, {"usher": 1})


async def test_points_need_the_capability(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    with pytest.raises(CapabilityDisabledError):
        await world.services.leaderboard.top(student, club.id)
    with pytest.raises(CapabilityDisabledError):
        await world.services.leaderboard.my_points(student, club.id)


async def test_attendance_stats_need_roster(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    await world.services.clubs.set_capabilities(su, club.id, {ClubCapability.POINTS})
    with pytest.raises(CapabilityDisabledError):
        await world.services.leaderboard.attendance(owner, club.id)


async def test_forms_need_the_capability(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor, su: Actor
) -> None:
    await world.services.memberships.join(student, club.id)
    await world.services.memberships.approve(owner, club.id, student.user_id)
    with pytest.raises(CapabilityDisabledError):
        await world.services.forms.save_profile(student, club.id, {"a": 1})
    await world.services.clubs.set_capabilities(su, club.id, {ClubCapability.FORMS})
    await world.services.forms.save_profile(student, club.id, {"a": 1})


async def test_profile_and_signup_are_member_only(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor, student: Actor
) -> None:
    await world.services.clubs.set_capabilities(su, club.id, {ClubCapability.FORMS})
    with pytest.raises(
        NotClubMemberError
    ):  # forms enabled, but the student never joined
        await world.services.forms.save_profile(student, club.id, {"a": 1})


async def test_banned_or_removed_member_cannot_sign_up(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    v = world.add_student()
    await world.services.memberships.join(v, comm.id)
    await world.services.memberships.approve(owner, comm.id, v.user_id)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})
    await world.services.memberships.ban(owner, comm.id, v.user_id, "x")
    with pytest.raises(NotClubMemberError):
        await world.services.drafts.signup(v, r.id, "usher", {})


async def test_round_needs_an_event_of_the_same_club(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, club, owner)  # event belongs to `club`, not `comm`
    with pytest.raises(DraftInvalidError):
        await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})


async def test_organizer_of_another_club_cannot_pick(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})
    rival = world.add_student()
    other = await world.services.clubs.create(
        rival, name="Rivals", slug="rivals-club", description="d"
    )
    await world.services.clubs.submit(rival, other.id)
    await world.services.clubs.review(su, other.id, approve=True, reason=None)
    with pytest.raises(PermissionDeniedError):
        await world.services.drafts.pick(rival, r.id, rival.user_id, "usher")


async def test_capability_revoked_after_the_round_opened_blocks_work(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    v = world.add_student()
    await world.services.memberships.join(v, comm.id)
    await world.services.memberships.approve(owner, comm.id, v.user_id)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})
    await world.services.clubs.set_capabilities(su, comm.id, {ClubCapability.POINTS})
    with pytest.raises(CapabilityDisabledError):
        await world.services.drafts.signup(v, r.id, "usher", {})
    with pytest.raises(CapabilityDisabledError):
        await world.services.drafts.pick(owner, r.id, v.user_id, "usher")


async def test_draft_signup_rank_pick_flow(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    vols = [world.add_student() for _ in range(3)]
    for v in vols:
        await world.services.memberships.join(v, comm.id)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 2})
    for v in vols:
        await world.services.drafts.signup(v, r.id, "usher", {})
    outsider = world.add_student()
    with pytest.raises(NotClubMemberError):
        await world.services.drafts.signup(outsider, r.id, "usher", {})
    ranked = await world.services.drafts.rank(owner, r.id)
    assert {x.user_id for x in ranked} == {v.user_id for v in vols}
    assert ranked == await world.services.drafts.rank(owner, r.id)  # deterministic
    p = await world.services.drafts.pick(owner, r.id, ranked[0].user_id, "usher")
    await world.services.drafts.invite(owner, p.id)
    assert any(
        n.type == NotificationType.DRAFT_INVITE and n.user_id == ranked[0].user_id
        for n in world.sent
    )


async def test_only_organizers_pick(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor, student: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})
    with pytest.raises(PermissionDeniedError):
        await world.services.drafts.pick(student, r.id, student.user_id, "usher")


async def test_no_show_job_writes_minus_four(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor, student: Actor
) -> None:
    comm = await _volunteers(world, owner, su)
    e = await _done_event(world, comm, owner)
    await world.services.memberships.join(student, comm.id)
    r = await world.services.drafts.open_round(owner, e.id, comm.id, {"usher": 1})
    await world.services.drafts.signup(student, r.id, "usher", {})
    p = await world.services.drafts.pick(owner, r.id, student.user_id, "usher")
    await world.services.drafts.invite(owner, p.id)
    await world.services.drafts.respond(student, p.id, accept=True)
    world.clock.set(e.ends_at + timedelta(hours=1, minutes=59))
    await world.services.events.finish(owner, e.id)
    assert (
        await world.services.drafts.mark_no_show_due() == 0
    )  # still in the grace period
    world.clock.set(e.ends_at + timedelta(hours=2, minutes=1))
    assert await world.services.drafts.mark_no_show_due() == 1
    assert await world.services.drafts.mark_no_show_due() == 0
    assert (await world.services.leaderboard.my_points(student, comm.id))["total"] == -4


async def test_check_in_awards_points_once_and_leaderboard_masks_opt_out(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor, su: Actor
) -> None:
    comm = await world.services.clubs.set_capabilities(
        su, club.id, ALL
    )  # points live on the club that runs the event
    other = world.add_student()
    e = await _done_event(world, club, owner)
    world.clock.set(e.starts_at - timedelta(minutes=10))  # inside the check-in window
    for u in (student, other):
        await world.services.events.rsvp(u, e.id)
        await world.services.events.check_in(owner, e.id, u.user_id, "manual")
        await world.services.events.check_in(
            owner, e.id, u.user_id, "manual"
        )  # repeat: no extra
    assert (await world.services.leaderboard.my_points(student, comm.id))["total"] == 2
    await world.services.leaderboard.set_opt_out(other, True)
    rows = await world.services.leaderboard.top(student, comm.id)
    assert [r.points for r in rows] == [2, 2]
    masked = [r for r in rows if r.user_id is None]
    assert len(masked) == 1 and masked[0].display_name.startswith("Student #")


async def test_check_in_outside_the_window_is_refused(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _done_event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    with pytest.raises(CheckInWindowError):  # 3 hours before the start
        await world.services.events.check_in(owner, e.id, student.user_id, "manual")
    world.clock.set(e.ends_at + timedelta(hours=1, minutes=1))
    with pytest.raises(CheckInWindowError):  # window closed at ends_at + 1h
        await world.services.events.check_in(owner, e.id, student.user_id, "manual")


async def test_non_organizer_cannot_check_in_others(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    e = await _done_event(world, club, owner)
    await world.services.events.rsvp(student, e.id)
    world.clock.set(e.starts_at - timedelta(minutes=10))
    with pytest.raises(PermissionDeniedError):
        await world.services.events.check_in(student, e.id, student.user_id, "manual")


async def test_analytics_matches_seeded_data(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    e = await _done_event(world, club, owner)
    users = [world.add_student() for _ in range(3)]
    for u in users:
        await world.services.events.rsvp(u, e.id)
    world.clock.set(e.starts_at - timedelta(minutes=10))
    await world.services.events.check_in(owner, e.id, users[0].user_id, "manual")
    o = await world.services.analytics.overview(su, None, None)
    assert o["clubs"]["active"] == 1 and o["events"] == 1
    assert o["rsvps"] == 3 and o["check_ins"] == 1
    with pytest.raises(PermissionDeniedError):
        await world.services.analytics.overview(users[0], None, None)


async def test_activities_admin_role_reads_analytics_but_cannot_approve(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    admin = world.add_staff(Role.ACTIVITIES_ADMIN)
    await world.services.analytics.overview(admin, None, None)
    c2 = await world.services.clubs.create(
        owner, name="X", slug="extra-club", description="d"
    )
    await world.services.clubs.submit(owner, c2.id)
    with pytest.raises(PermissionDeniedError):
        await world.services.clubs.review(admin, c2.id, approve=True, reason=None)


# ---- public -------------------------------------------------------------------


async def test_public_listing_only_active_public_clubs(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    hidden = await world.services.clubs.create(
        owner, name="Draft", slug="draft-club", description="d"
    )
    slugs = {c.slug for c in await world.services.public.list_clubs()}
    assert club.slug in slugs and hidden.slug not in slugs
    with pytest.raises(NotFoundError):
        await world.services.public.get_club(hidden.slug)


async def _contact(
    world: ActivitiesWorld, club: Club, telegram: bool = True, **kw: Any
) -> Any:
    if telegram:  # every member of the club (its owner) has linked Telegram
        members = await world.ports.members.list(club.id)
        world.relay.reachable_ids.update(m.user_id for m in members)
    args = {
        "name": "Vera",
        "email": "v@example.com",
        "message": "Hello",
        "captcha_token": "ok",
        "honeypot": "",
        "ip": "203.0.113.1",
    }
    args.update(kw)
    return await world.services.public.submit_contact(club.slug, **args)


async def test_contact_goes_only_to_the_owner_telegram(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    await world.services.memberships.join(student, club.id)
    await _contact(world, club)
    assert [
        (d["user_id"], d["name"], d["email"], d["body"]) for d in world.relay.delivered
    ] == [(owner.user_id, "Vera", "v@example.com", "Hello")]
    assert not [
        n for n in world.sent if "v@example.com" in repr(n) or "Hello" in repr(n)
    ]


async def test_contact_needs_an_owner_with_telegram(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    with pytest.raises(ContactUnavailableError):
        await _contact(world, club, telegram=False)
    assert not world.relay.delivered


async def test_contact_rate_limit_is_also_per_ip_across_clubs(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    o2 = world.add_student()
    c2 = await world.services.clubs.create(
        o2, name="Art", slug="art-club", description="d"
    )
    await world.services.clubs.submit(o2, c2.id)
    await world.services.clubs.review(su, c2.id, approve=True, reason=None)
    await world.services.clubs.update(o2, c2.id, contact_enabled=True)
    for _ in range(3):
        await _contact(world, club)
    await _contact(world, c2, ip="203.0.113.2")  # another address is unaffected
    for _ in range(
        2
    ):  # 5/hour per address over all clubs (3 + 2); c2 alone is under its cap
        await _contact(world, c2)
    with pytest.raises(RateLimitedError):
        await _contact(world, c2)


async def test_contact_disabled_by_default(world: ActivitiesWorld, club: Club) -> None:
    with pytest.raises(ContactNotAcceptedError):
        await _contact(world, club)


async def test_contact_honeypot_is_silent(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    await _contact(world, club, honeypot="bot")
    assert not world.relay.delivered


async def test_contact_bad_captcha(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    world.captcha.ok = False
    with pytest.raises(CaptchaFailedError):
        await _contact(world, club)


async def test_contact_rate_limit_three_per_hour(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, contact_enabled=True)
    for _ in range(3):
        await _contact(world, club)
    with pytest.raises(RateLimitedError):
        await _contact(world, club)
    world.clock.advance(hours=1, minutes=1)
    await _contact(world, club)
