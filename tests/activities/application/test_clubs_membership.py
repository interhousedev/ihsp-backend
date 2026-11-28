"""ClubService, MembershipService, OwnershipService (spec 4.5, phase 1 exit).

Services (on world.services) the implementation must provide:
  clubs.create(actor, name, slug, description, **kw)->Club; .submit(actor, club_id);
    .review(su, club_id, approve, reason); .suspend(actor, club_id, reason); .get(actor,
    club_id);
    .update(actor, club_id, **fields); .list_mine(actor)
  memberships.join(actor, club_id, message=None); .approve(actor, club_id, user_id);
    .leave(actor, club_id); .ban(actor, club_id, user_id, reason); .list(actor, club_id)
  ownership.offer(actor, club_id, to_user_id); .accept(actor, transfer_id);
  .decline(actor, transfer_id);
    .cancel(actor, transfer_id); .force_transfer(su, club_id, to_user_id); .expire_due()
    -> int;
    .graduation_alerts() -> int (notifies owners of graduating students)
  Errors: app.modules.activities.domain.club.{ClubStateError},
  access.{PermissionDeniedError},
    app.shared.base_error.NotFoundError
"""

from uuid import UUID

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.club import Club
from app.modules.activities.domain.ownership import TRANSFER_TTL
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError, NotFoundError
from app.shared.notifications import NotificationType
from tests.fakes.activities.world import ActivitiesWorld

import pytest


async def test_only_su_can_approve(
    world: ActivitiesWorld, owner: Actor, student: Actor
) -> None:
    c = await world.services.clubs.create(
        owner, name="Go", slug="go-club", description="d"
    )
    await world.services.clubs.submit(owner, c.id)
    with pytest.raises(PermissionDeniedError):
        await world.services.clubs.review(owner, c.id, approve=True, reason=None)
    su = world.add_staff(Role.SU)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    assert (await world.services.clubs.get(owner, c.id)).status == "active"


async def test_state_persists_on_reload(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    again = await world.services.clubs.get(owner, club.id)
    assert again.status == "active" and again.owner_id == owner.user_id


async def test_join_approve_leave(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await world.services.memberships.join(student, club.id)
    assert any(
        n.type == NotificationType.CLUB_JOIN_REQUEST and n.user_id == owner.user_id
        for n in world.sent
    )
    await world.services.memberships.approve(owner, club.id, student.user_id)
    assert any(
        n.type == NotificationType.CLUB_JOIN_RESULT and n.user_id == student.user_id
        for n in world.sent
    )
    await world.services.memberships.leave(student, club.id)
    members = await world.services.memberships.list(owner, club.id)
    assert student.user_id not in {m.user_id for m in members if m.status == "active"}


async def test_plain_student_cannot_approve_or_ban(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    other = world.add_student()
    await world.services.memberships.join(other, club.id)
    with pytest.raises(PermissionDeniedError):
        await world.services.memberships.approve(student, club.id, other.user_id)
    with pytest.raises(PermissionDeniedError):
        await world.services.memberships.ban(student, club.id, other.user_id, "x")


async def test_banned_member_cannot_rejoin(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await world.services.memberships.join(student, club.id)
    await world.services.memberships.approve(owner, club.id, student.user_id)
    await world.services.memberships.ban(owner, club.id, student.user_id, "spam")
    with pytest.raises(BaseError):
        await world.services.memberships.join(student, club.id)


async def test_declined_request_can_be_sent_again(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, join_policy="request")
    await world.services.memberships.join(student, club.id)
    m = await world.services.memberships.decline(owner, club.id, student.user_id)
    assert m.status == "removed"
    with pytest.raises(BaseError):
        await world.services.memberships.decline(owner, club.id, student.user_id)
    again = await world.services.memberships.join(student, club.id)
    assert again.status == "requested"


async def test_removed_member_can_rejoin_and_owner_stays(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await world.services.clubs.update(owner, club.id, join_policy="request")
    await world.services.memberships.join(student, club.id)
    with pytest.raises(BaseError):
        await world.services.memberships.remove(owner, club.id, student.user_id)
    await world.services.memberships.approve(owner, club.id, student.user_id)
    m = await world.services.memberships.remove(owner, club.id, student.user_id)
    assert m.status == "removed"
    members = await world.services.memberships.list(owner, club.id)
    assert student.user_id not in {x.user_id for x in members if x.status == "active"}
    assert (await world.services.memberships.join(student, club.id)).status in (
        "requested",
        "active",
    )
    with pytest.raises(BaseError):
        await world.services.memberships.remove(owner, club.id, owner.user_id)


async def test_plain_student_cannot_decline_or_remove(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    other = world.add_student()
    await world.services.memberships.join(other, club.id)
    with pytest.raises(PermissionDeniedError):
        await world.services.memberships.decline(student, club.id, other.user_id)
    with pytest.raises(PermissionDeniedError):
        await world.services.memberships.remove(student, club.id, other.user_id)


async def test_idor_membership_of_another_club(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    other_owner = world.add_student()
    c2 = await world.services.clubs.create(
        other_owner, name="Art", slug="art-club", description="d"
    )
    await world.services.clubs.submit(other_owner, c2.id)
    await world.services.clubs.review(
        su, c2.id, approve=True, reason=None
    )  # active: joins are legal
    victim = world.add_student()
    await world.services.memberships.join(victim, c2.id)
    # owner of club 1 targets a member of club 2 through club 1's path
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        await world.services.memberships.ban(owner, club.id, victim.user_id, "x")
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        await world.services.memberships.approve(owner, c2.id, victim.user_id)


async def test_only_active_clubs_accept_members(
    world: ActivitiesWorld, owner: Actor, su: Actor, student: Actor
) -> None:
    from app.modules.activities.domain.club import ClubStateError

    c = await world.services.clubs.create(
        owner, name="Late", slug="late-club", description="d"
    )
    with pytest.raises(ClubStateError):  # draft
        await world.services.memberships.join(student, c.id)
    await world.services.clubs.submit(owner, c.id)
    with pytest.raises(ClubStateError):  # pending_review
        await world.services.memberships.join(student, c.id)
    await world.services.clubs.review(su, c.id, approve=True, reason=None)
    await world.services.memberships.join(student, c.id)  # active: allowed
    await world.services.clubs.suspend(su, c.id, "violation")
    with pytest.raises(ClubStateError):  # suspended
        await world.services.memberships.join(world.add_student(), c.id)


async def _member(
    world: ActivitiesWorld, club: Club, owner: Actor, user: UUID | None
) -> None:
    await world.services.memberships.join(user, club.id)
    await world.services.memberships.approve(owner, club.id, user.user_id)


async def test_transfer_accept_changes_the_owner(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await _member(world, club, owner, student)
    t = await world.services.ownership.offer(owner, club.id, student.user_id)
    assert any(
        n.type == NotificationType.CLUB_TRANSFER_OFFER and n.user_id == student.user_id
        for n in world.sent
    )
    with pytest.raises(PermissionDeniedError):
        await world.services.ownership.accept(owner, t.id)  # only the recipient accepts
    await world.services.ownership.accept(student, t.id)
    assert (
        await world.services.clubs.get(student, club.id)
    ).owner_id == student.user_id


async def test_transfer_decline_and_cancel_keep_the_owner(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await _member(world, club, owner, student)
    t = await world.services.ownership.offer(owner, club.id, student.user_id)
    await world.services.ownership.decline(student, t.id)
    t2 = await world.services.ownership.offer(owner, club.id, student.user_id)
    await world.services.ownership.cancel(owner, t2.id)
    assert (await world.services.clubs.get(owner, club.id)).owner_id == owner.user_id


async def test_offer_requires_membership_of_the_recipient(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    with pytest.raises(BaseError):
        await world.services.ownership.offer(owner, club.id, student.user_id)


async def test_transfer_expires_after_ttl(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await _member(world, club, owner, student)
    t = await world.services.ownership.offer(owner, club.id, student.user_id)
    world.clock.advance(seconds=TRANSFER_TTL.total_seconds() + 1)
    assert await world.services.ownership.expire_due() == 1
    with pytest.raises(BaseError):
        await world.services.ownership.accept(student, t.id)
    assert (await world.services.clubs.get(owner, club.id)).owner_id == owner.user_id


async def test_force_transfer_is_su_only(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor, su: Actor
) -> None:
    await _member(world, club, owner, student)
    with pytest.raises(PermissionDeniedError):
        await world.services.ownership.force_transfer(owner, club.id, student.user_id)
    await world.services.ownership.force_transfer(su, club.id, student.user_id)
    assert (await world.services.clubs.get(su, club.id)).owner_id == student.user_id


async def test_suspended_club_is_hidden_from_public(
    world: ActivitiesWorld, club: Club, su: Actor
) -> None:
    await world.services.clubs.suspend(su, club.id, "violation")
    assert club.slug not in {c.slug for c in await world.services.public.list_clubs()}
    with pytest.raises(NotFoundError):
        await world.services.public.get_club(club.slug)


async def test_transfer_offer_is_listed_and_answers_reach_the_offerer(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    await _member(world, club, owner, student)
    t = await world.services.ownership.offer(owner, club.id, student.user_id)
    offer = next(
        n
        for n in world.sent
        if n.type == NotificationType.CLUB_TRANSFER_OFFER
        and n.user_id == student.user_id
    )
    assert offer.payload["transfer_id"] == str(t.id)
    assert "club_name" in offer.payload and "result" not in offer.payload

    assert [x.id for x in await world.services.ownership.incoming(student)] == [t.id]
    assert await world.services.ownership.incoming(owner) == []

    await world.services.ownership.decline(student, t.id)
    assert await world.services.ownership.incoming(student) == []
    answer = [
        n
        for n in world.sent
        if n.user_id == owner.user_id and n.payload.get("result") == "declined"
    ]
    assert len(answer) == 1
