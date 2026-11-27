"""Club, Declaration, Membership, OwnershipTransfer, access (spec 4.3-4.4).

The implementation must provide, under `app.modules.activities.domain`:
  club: ClubKind (club|su; no `community`), ClubStatus
  (draft|pending_review|active|suspended|archived),
    JoinPolicy (open|request|invite), Club(id, slug, kind, name, status, join_policy,
    visibility_public, contact_enabled, logo_file_id, published_once, created_by)
    Club.submit(), Club.review(approve: bool, reason, by_su: bool), Club.suspend(),
    Club.archive(),
    Club.rename_slug(new) ; SLUG_RE ; ClubInvalidError, ClubStateError (DomainError)
    Declaration(club_id, version, goals, rules, meeting_schedule, requirements, ...)
    frozen;
    next_declaration(previous: Declaration|None, **texts) -> Declaration (version + 1,
    never mutates)
  membership: MemberRole (owner|co_owner|team|member), MemberStatus
    (requested|active|left|removed|banned), Membership(club_id, user_id, role, status,
    declaration_version, joined_at, left_at), join(club, user_id, *,
    declaration_version, now,
    is_student=True) -> Membership (ONLY an `active` club accepts joins: draft,
    pending_review, suspended and
    archived raise ClubStateError) ('open' -> active, 'request' -> requested, 'invite'
    ->
    JoinNotAllowedError), Membership.approve(now), .leave(now), .remove(), .ban(),
    MembershipStateError, OwnerCannotLeaveError, NotStudentError, .can_rejoin() (False
    when banned)
  ownership: TransferStatus (offered|accepted|declined|cancelled|expired),
    OwnershipTransfer.offer(club_id, from_user, to_user, now, to_is_active_member:
    bool),
    .accept(now, members) -> OwnershipChange (swap roles), .decline(), .cancel(),
    .expire(now),
    TRANSFER_TTL == timedelta(days=7); TransferError
  access: Permission (VIEW_MEMBERS, EDIT_CLUB, EDIT_EVENTS, ANNOUNCE, APPROVE, TRANSFER,
    SEE_RATINGS_FULL), club_permissions(role, *, announce_allowed=False) -> frozenset
    (table in spec 4.4); global_permissions(actor_roles) for Role.SU /
    Role.ACTIVITIES_ADMIN
  app.shared.actor.Role gains SU = "su", ACTIVITIES_ADMIN = "activities_admin"
Boring choices: published_once flips on first approve; ADMIN implies ACTIVITIES_ADMIN.
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.modules.activities.domain.access import (
    Permission,
    club_permissions,
    global_permissions,
)
from app.modules.activities.domain.club import (
    SLUG_RE,
    Club,
    ClubInvalidError,
    ClubKind,
    ClubStateError,
    ClubStatus,
    JoinPolicy,
    next_declaration,
)
from app.modules.activities.domain.membership import (
    JoinNotAllowedError,
    MemberRole,
    Membership,
    MembershipStateError,
    MemberStatus,
    NotStudentError,
    OwnerCannotLeaveError,
    join,
)
from app.modules.activities.domain.ownership import (
    TRANSFER_TTL,
    OwnershipTransfer,
    TransferError,
    TransferStatus,
)
from app.shared.actor import Role

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)
NAME = {"uz": "a", "ru": "b", "en": "c"}


def active_club(**kw: object) -> Club:
    """A published club: the only state that accepts members."""
    return club(status=ClubStatus.ACTIVE, published_once=True, **kw)


def club(**kw: object) -> Club:
    base: dict[str, object] = {
        "id": uuid4(),
        "slug": "chess-club",
        "kind": ClubKind.CLUB,
        "name": NAME,
        "status": ClubStatus.DRAFT,
        "join_policy": JoinPolicy.OPEN,
        "visibility_public": True,
        "contact_enabled": True,
        "logo_file_id": None,
        "published_once": False,
        "created_by": uuid4(),
    }
    base.update(kw)
    return Club(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("slug", ["abc", "chess-club", "a1-b2", "x" * 40])
def test_valid_slugs(slug: str) -> None:
    assert SLUG_RE.fullmatch(slug)


@pytest.mark.parametrize("slug", ["ab", "Chess", "chess_club", "x" * 41, "a b c", ""])
def test_invalid_slugs(slug: str) -> None:
    assert not SLUG_RE.fullmatch(slug)
    with pytest.raises(ClubInvalidError):
        club(slug=slug).validate()


def test_club_lifecycle_needs_su_to_activate() -> None:
    c = club()
    c.submit()
    assert c.status == ClubStatus.PENDING_REVIEW
    with pytest.raises(ClubStateError):
        c.review(approve=True, reason=None, by_su=False)
    assert c.status == ClubStatus.PENDING_REVIEW
    c.review(approve=True, reason=None, by_su=True)
    assert c.status == ClubStatus.ACTIVE and c.published_once


def test_rejection_returns_to_draft_with_a_reason() -> None:
    c = club()
    c.submit()
    with pytest.raises(ClubInvalidError):
        c.review(approve=False, reason="", by_su=True)
    c.review(approve=False, reason="Needs a declaration", by_su=True)
    assert c.status == ClubStatus.DRAFT


def test_only_a_draft_can_be_submitted() -> None:
    c = club(status=ClubStatus.ACTIVE)
    with pytest.raises(ClubStateError):
        c.submit()


def test_slug_is_frozen_after_first_publication() -> None:
    c = club()
    c.rename_slug("chess-2")  # still free while never published
    c.submit()
    c.review(approve=True, reason=None, by_su=True)
    with pytest.raises(ClubStateError):
        c.rename_slug("chess-3")
    c.suspend()
    with pytest.raises(ClubStateError):
        c.rename_slug("chess-3")


def test_suspend_and_archive_only_from_active() -> None:
    c = club(status=ClubStatus.ACTIVE, published_once=True)
    c.suspend()
    assert c.status == ClubStatus.SUSPENDED
    with pytest.raises(ClubStateError):
        c.suspend()
    d = club(status=ClubStatus.ACTIVE, published_once=True)
    d.archive()
    assert d.status == ClubStatus.ARCHIVED


def test_declarations_are_append_only_and_versioned() -> None:
    v1 = next_declaration(
        None,
        club_id=uuid4(),
        goals=NAME,
        rules=NAME,
        meeting_schedule=NAME,
        requirements=NAME,
    )
    v2 = next_declaration(
        v1,
        goals=NAME,
        rules={**NAME, "en": "new"},
        meeting_schedule=NAME,
        requirements=NAME,
    )
    assert (v1.version, v2.version) == (1, 2)
    assert v1.rules["en"] == "c" and v2.club_id == v1.club_id
    with pytest.raises(FrozenInstanceError):
        v1.version = 9  # type: ignore[misc]


# ---- membership ---------------------------------------------------------------


def test_open_club_activates_and_records_declaration_version() -> None:
    m = join(active_club(), uuid4(), declaration_version=3, now=NOW)
    assert (m.status, m.role, m.declaration_version) == (
        MemberStatus.ACTIVE,
        MemberRole.MEMBER,
        3,
    )
    assert m.joined_at == NOW


def test_request_policy_needs_approval() -> None:
    m = join(
        active_club(join_policy=JoinPolicy.REQUEST),
        uuid4(),
        declaration_version=1,
        now=NOW,
    )
    assert m.status == MemberStatus.REQUESTED
    m.approve(NOW)
    assert m.status == MemberStatus.ACTIVE


def test_invite_only_clubs_reject_self_join() -> None:
    with pytest.raises(JoinNotAllowedError):
        join(
            active_club(join_policy=JoinPolicy.INVITE),
            uuid4(),
            declaration_version=1,
            now=NOW,
        )


def test_only_students_join() -> None:
    with pytest.raises(NotStudentError):
        join(active_club(), uuid4(), declaration_version=1, now=NOW, is_student=False)


@pytest.mark.parametrize(
    "status",
    [
        ClubStatus.DRAFT,
        ClubStatus.PENDING_REVIEW,
        ClubStatus.SUSPENDED,
        ClubStatus.ARCHIVED,
    ],
)
def test_only_active_clubs_accept_members(status: ClubStatus) -> None:
    for policy in (JoinPolicy.OPEN, JoinPolicy.REQUEST):
        with pytest.raises(ClubStateError):
            join(
                club(status=status, join_policy=policy),
                uuid4(),
                declaration_version=1,
                now=NOW,
            )
    join(active_club(), uuid4(), declaration_version=1, now=NOW)


def test_leave_records_time_and_is_final() -> None:
    m = join(active_club(), uuid4(), declaration_version=1, now=NOW)
    m.leave(NOW + timedelta(days=1))
    assert (m.status, m.left_at) == (MemberStatus.LEFT, NOW + timedelta(days=1))
    with pytest.raises(MembershipStateError):  # nothing active to leave
        m.leave(NOW)


def test_owner_cannot_leave_without_transfer() -> None:
    m = Membership(
        uuid4(), uuid4(), MemberRole.OWNER, MemberStatus.ACTIVE, 1, NOW, None
    )
    with pytest.raises(OwnerCannotLeaveError):
        m.leave(NOW)


def test_banned_members_cannot_rejoin() -> None:
    m = join(active_club(), uuid4(), declaration_version=1, now=NOW)
    m.ban()
    assert m.status == MemberStatus.BANNED
    assert not m.can_rejoin()


# ---- ownership transfer -------------------------------------------------------


def _members(owner: Membership, target: Membership) -> dict:
    return {owner.user_id: owner, target.user_id: target}


def _pair() -> Any:
    cid = uuid4()
    owner = Membership(
        cid, uuid4(), MemberRole.OWNER, MemberStatus.ACTIVE, 1, NOW, None
    )
    target = Membership(
        cid, uuid4(), MemberRole.MEMBER, MemberStatus.ACTIVE, 1, NOW, None
    )
    return cid, owner, target


def test_offer_needs_an_active_member_target() -> None:
    cid, owner, target = _pair()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    assert t.status == TransferStatus.OFFERED and t.expires_at == NOW + TRANSFER_TTL
    assert TRANSFER_TTL == timedelta(days=7)
    with pytest.raises(TransferError):
        OwnershipTransfer.offer(
            cid, owner.user_id, uuid4(), NOW, to_is_active_member=False
        )
    with pytest.raises(TransferError):
        OwnershipTransfer.offer(
            cid, owner.user_id, owner.user_id, NOW, to_is_active_member=True
        )


def test_accept_swaps_roles_in_one_step() -> None:
    cid, owner, target = _pair()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    t.accept(NOW + timedelta(days=1), _members(owner, target))
    assert t.status == TransferStatus.ACCEPTED
    assert (owner.role, target.role) == (MemberRole.CO_OWNER, MemberRole.OWNER)


def test_accept_fails_when_target_left_and_changes_nothing() -> None:
    cid, owner, target = _pair()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    target.leave(NOW)
    with pytest.raises(TransferError):
        t.accept(NOW, _members(owner, target))
    assert owner.role == MemberRole.OWNER and t.status == TransferStatus.OFFERED


def test_accept_after_expiry_is_refused() -> None:
    cid, owner, target = _pair()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    with pytest.raises(TransferError):
        t.accept(NOW + TRANSFER_TTL + timedelta(seconds=1), _members(owner, target))


def test_decline_cancel_expire_are_terminal() -> None:
    cid, owner, target = _pair()
    for action, status in (
        ("decline", TransferStatus.DECLINED),
        ("cancel", TransferStatus.CANCELLED),
    ):
        t = OwnershipTransfer.offer(
            cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
        )
        getattr(t, action)()
        assert t.status == status
        with pytest.raises(TransferError):
            t.decline()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    t.expire(NOW + TRANSFER_TTL + timedelta(seconds=1))
    assert t.status == TransferStatus.EXPIRED


def test_expire_does_nothing_before_the_deadline() -> None:
    cid, owner, target = _pair()
    t = OwnershipTransfer.offer(
        cid, owner.user_id, target.user_id, NOW, to_is_active_member=True
    )
    t.expire(NOW + timedelta(days=6))
    assert t.status == TransferStatus.OFFERED


# ---- access -------------------------------------------------------------------


def test_member_permissions() -> None:
    assert club_permissions(MemberRole.MEMBER) == {Permission.VIEW_MEMBERS}


def test_team_may_run_events_and_announce_only_if_allowed() -> None:
    p = club_permissions(MemberRole.TEAM)
    assert Permission.EDIT_EVENTS in p and Permission.ANNOUNCE not in p
    assert Permission.ANNOUNCE in club_permissions(
        MemberRole.TEAM, announce_allowed=True
    )
    assert Permission.EDIT_CLUB not in p and Permission.APPROVE not in p


def test_co_owner_and_owner_tables() -> None:
    co = club_permissions(MemberRole.CO_OWNER)
    assert {
        Permission.EDIT_CLUB,
        Permission.EDIT_EVENTS,
        Permission.ANNOUNCE,
        Permission.APPROVE,
        Permission.SEE_RATINGS_FULL,
    } <= co
    assert Permission.TRANSFER not in co
    assert Permission.TRANSFER in club_permissions(MemberRole.OWNER)


def test_global_roles() -> None:
    su = global_permissions({Role.SU})
    assert {
        Permission.EDIT_CLUB,
        Permission.EDIT_EVENTS,
        Permission.APPROVE,
        Permission.TRANSFER,
    } <= su
    adm = global_permissions({Role.ACTIVITIES_ADMIN})
    assert Permission.TRANSFER in adm and Permission.EDIT_CLUB in adm
    assert Permission.EDIT_EVENTS not in adm
    assert global_permissions({Role.ADMIN}) == adm  # ADMIN implies ACTIVITIES_ADMIN
    assert global_permissions({Role.STUDENT}) == frozenset()
