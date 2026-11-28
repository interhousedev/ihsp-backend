"""Club capabilities replace the Community entity; ClubCourseLink (spec 4.3).

The implementation must provide, under `app.modules.activities.domain`:
  club: ClubKind (club|su only: NO `community` member), ClubCapability
  (forms|drafting|points|roster),
    Club.capabilities: frozenset[ClubCapability] (default empty), Club.enable(cap, *,
    by_su: bool),
    Club.disable(cap, *, by_su: bool) (only SU toggles: CapabilityDeniedError),
    Club.require(cap)
    (CapabilityDisabledError when off). Enabling `drafting` implies `forms`.
  draft: DraftRound.open(event_id, club_id, needed, *, club, event_club_id) requires
  ClubCapability.DRAFTING on
    the club; DraftSignup.submit(round, user_id, role, answers, is_club_member).
  course_link: two-party consent. ClubCourseLink(club_id, course_id, requested_by,
  requested_side
    'club'|'course', status 'pending'|'active', requested_at, confirmed_by,
    confirmed_at).
    request_link(club_id, course_id, by_user, *, is_club_owner,
    is_course_owner_or_teacher, existing, now):
    the requester holds at least one side (else CourseLinkDeniedError); one side ->
    status 'pending'
    (requested_side = the side held); both sides held by the same person -> 'active' at
    once; an existing
    pending/active pair -> CourseLinkExistsError.
    confirm(link, by_user, *, is_club_owner, is_course_owner_or_teacher, now): only the
    OTHER side confirms
    (CourseLinkDeniedError for the requester's own side, for a stranger, and for anyone
    whose scope is
    false NOW); a non-pending link -> CourseLinkStateError.
    unlink(link, *, is_club_owner, is_course_owner_or_teacher): either side, pending or
    active.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.domain.club import (
    CapabilityDeniedError,
    CapabilityDisabledError,
    Club,
    ClubCapability,
    ClubKind,
)
from app.modules.activities.domain.course_link import (
    ClubCourseLink,
    CourseLinkDeniedError,
    CourseLinkExistsError,
    CourseLinkStateError,
    confirm,
    request_link,
    unlink,
)
from app.modules.activities.domain.draft import DraftRound

import pytest

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def _club() -> Club:
    return Club(
        id=uuid4(),
        slug="volunteers",
        kind=ClubKind.CLUB,
        name="IHT Volunteers",
        created_by=uuid4(),
    )


def test_community_kind_is_gone() -> None:
    assert {k.value for k in ClubKind} == {"club", "su"}


def test_capabilities_default_off_and_su_only_toggle() -> None:
    c = _club()
    assert c.capabilities == frozenset()
    with pytest.raises(CapabilityDeniedError):
        c.enable(ClubCapability.POINTS, by_su=False)
    c.enable(ClubCapability.POINTS, by_su=True)
    assert ClubCapability.POINTS in c.capabilities
    c.disable(ClubCapability.POINTS, by_su=True)
    assert c.capabilities == frozenset()


def test_drafting_implies_forms_and_require() -> None:
    c = _club()
    c.enable(ClubCapability.DRAFTING, by_su=True)
    assert ClubCapability.FORMS in c.capabilities
    with pytest.raises(CapabilityDisabledError):
        c.require(ClubCapability.ROSTER)


def test_draft_round_needs_drafting_capability() -> None:
    c = _club()
    with pytest.raises(CapabilityDisabledError):
        DraftRound.open(uuid4(), c.id, {"usher": 2}, club=c, event_club_id=c.id)
    c.enable(ClubCapability.DRAFTING, by_su=True)
    r = DraftRound.open(uuid4(), c.id, {"usher": 2}, club=c, event_club_id=c.id)
    assert r.club_id == c.id


CLUB, COURSE = {"is_club_owner": True, "is_course_owner_or_teacher": False}, {
    "is_club_owner": False,
    "is_course_owner_or_teacher": True,
}
BOTH = {"is_club_owner": True, "is_course_owner_or_teacher": True}
NEITHER = {"is_club_owner": False, "is_course_owner_or_teacher": False}


def _request(
    side: dict, user: UUID | None = None, existing: Iterable[UUID] = ()
) -> Any:
    return request_link(
        uuid4(), uuid4(), user or uuid4(), existing=list(existing), now=NOW, **side
    )


def test_request_needs_one_side_and_waits_for_the_other() -> None:
    with pytest.raises(CourseLinkDeniedError):
        _request(NEITHER)
    mine = uuid4()
    ln = _request(CLUB, mine)
    assert isinstance(ln, ClubCourseLink)
    assert (ln.status, ln.requested_side, ln.requested_by) == ("pending", "club", mine)
    assert _request(COURSE).requested_side == "course"


def test_confirmation_must_come_from_the_other_side_with_a_live_scope() -> None:
    ln = _request(CLUB)
    for bad in (CLUB, NEITHER):  # own side again / a stranger
        with pytest.raises(CourseLinkDeniedError):
            confirm(ln, uuid4(), now=NOW + timedelta(hours=1), **bad)
    assert ln.status == "pending"
    other = uuid4()
    confirm(ln, other, now=NOW + timedelta(hours=1), **COURSE)
    assert (ln.status, ln.confirmed_by, ln.confirmed_at) == (
        "active",
        other,
        NOW + timedelta(hours=1),
    )
    with pytest.raises(CourseLinkStateError):
        confirm(ln, other, now=NOW, **COURSE)
    back = _request(COURSE)  # reverse direction: the club owner confirms
    with pytest.raises(CourseLinkDeniedError):
        confirm(back, uuid4(), now=NOW, **COURSE)
    confirm(back, uuid4(), now=NOW, **CLUB)


def test_one_person_holding_both_sides_activates_at_once() -> None:
    assert _request(BOTH).status == "active"


def test_duplicate_pair_pending_or_active_and_unlink_by_either_side() -> None:
    club_id, course_id, user = uuid4(), uuid4(), uuid4()
    ln = request_link(club_id, course_id, user, existing=[], now=NOW, **CLUB)
    with pytest.raises(
        CourseLinkExistsError
    ):  # pending already blocks a second request
        request_link(club_id, course_id, user, existing=[ln], now=NOW, **COURSE)
    unlink(ln, **COURSE)  # the course side declines the pending request
    assert ln.status == "ended"
    ln2 = request_link(
        club_id, course_id, user, existing=[ln], now=NOW, **COURSE
    )  # ended pair may return
    confirm(ln2, uuid4(), now=NOW, **CLUB)
    unlink(ln2, **CLUB)
    ln3 = request_link(club_id, course_id, user, existing=[], now=NOW, **BOTH)
    unlink(ln3, **COURSE)
    ln4 = request_link(club_id, course_id, user, existing=[], now=NOW, **BOTH)
    with pytest.raises(CourseLinkDeniedError):
        unlink(ln4, **NEITHER)
