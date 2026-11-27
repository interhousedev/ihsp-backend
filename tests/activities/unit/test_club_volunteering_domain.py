"""Volunteering as club capabilities: forms, drafting, points, roster (spec 4.14;
replaces the Community tests).

IHT Volunteers is a Club whose `capabilities` include drafting/forms/points/roster;
there is no Community entity.
The implementation must provide, under `app.modules.activities.domain`:
  draft: ClubProfile(user_id, club_id, answers, updated_at).upsert(answers, now) (needs
  the `forms`
    capability); DraftRound.open(event_id, club_id, needed: dict[str,int], *, club,
    event_club_id) status open|closed; the event must belong to the
    same club (event_club_id != club_id: DraftInvalidError); needs
    ClubCapability.DRAFTING on `club` (CapabilityDisabledError otherwise);
    DraftRound.close();
    DraftSignup.submit(round, user_id, role, answers, is_club_member, existing=()) where
    is_club_member means an ACTIVE membership (not left/removed/banned) (one per
    (round,user):
    DuplicateSignupError; only club members: NotClubMemberError; closed round:
    RoundClosedError; role not in
    round.needed: DraftInvalidError); DraftSignup.withdraw(); DraftPick status
    proposed|invited|accepted|declined|no_show|completed with transitions
    proposed->invited->accepted|declined,
    accepted->completed|no_show (DraftPickStateError); DraftPick.propose(round, user_id,
    role, filled)
    refuses a full role (RoleFullError). The round carries `club_id`.
  ranking and points: unchanged (see the points/ranking contract in the previous
  revision):
    rank_candidates, DEFAULT_POINTS, entry_for, add_entry, total, top.
  club.require(ClubCapability.POINTS) / ROSTER guard points and attendance stats
  (service layer; see
  test_club_points_public.py).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.activities.domain.club import (
    CapabilityDisabledError,
    Club,
    ClubCapability,
    ClubKind,
)
from app.modules.activities.domain.draft import (
    ClubProfile,
    DraftInvalidError,
    DraftPick,
    DraftPickStateError,
    DraftRound,
    DraftSignup,
    DuplicateSignupError,
    NotClubMemberError,
    RoleFullError,
    RoundClosedError,
)
from app.modules.activities.domain.points import (
    DEFAULT_POINTS,
    add_entry,
    entry_for,
    top,
    total,
)
from app.modules.activities.domain.ranking import (
    Candidate,
    Requirements,
    rank_candidates,
)

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)


def volunteers(*caps: ClubCapability) -> Club:
    club = Club(
        id=uuid4(),
        slug="volunteers",
        kind=ClubKind.CLUB,
        name="IHT Volunteers",
        created_by=uuid4(),
    )
    for cap in caps:
        club.enable(cap, by_su=True)
    return club


def rnd(**kw: object) -> DraftRound:
    club = volunteers(ClubCapability.DRAFTING)
    return DraftRound.open(
        event_id=uuid4(),
        club_id=club.id,
        needed=kw.get("needed", {"usher": 2, "mc": 1}),
        club=club,  # type: ignore[arg-type]
        event_club_id=club.id,
    )


def test_round_belongs_to_the_club_and_needs_drafting() -> None:
    club = volunteers(ClubCapability.DRAFTING)
    assert (
        DraftRound.open(
            event_id=uuid4(),
            club_id=club.id,
            needed={"usher": 1},
            club=club,
            event_club_id=club.id,
        ).club_id
        == club.id
    )
    with pytest.raises(CapabilityDisabledError):
        DraftRound.open(
            event_id=uuid4(),
            club_id=club.id,
            needed={"usher": 1},
            club=volunteers(ClubCapability.POINTS),
            event_club_id=club.id,
        )


def test_round_refuses_an_event_of_another_club() -> None:
    club = volunteers(ClubCapability.DRAFTING)
    with pytest.raises(DraftInvalidError):
        DraftRound.open(
            event_id=uuid4(),
            club_id=club.id,
            needed={"usher": 1},
            club=club,
            event_club_id=uuid4(),
        )


def test_drafting_brings_forms_and_all_four_capabilities_fit_one_club() -> None:
    club = volunteers(ClubCapability.DRAFTING)
    assert ClubCapability.FORMS in club.capabilities
    full = volunteers(*ClubCapability)
    assert full.capabilities == frozenset(ClubCapability)


def test_profile_upsert_replaces_answers() -> None:
    p = ClubProfile(uuid4(), uuid4(), {"a": 1}, NOW)
    p.upsert({"a": 2}, NOW + timedelta(days=1))
    assert p.answers == {"a": 2} and p.updated_at == NOW + timedelta(days=1)


def test_signup_rules() -> None:
    r, u = rnd(), uuid4()
    s = DraftSignup.submit(r, u, "usher", {}, is_club_member=True)
    assert s.status == "submitted"
    with pytest.raises(DuplicateSignupError):
        DraftSignup.submit(r, u, "usher", {}, is_club_member=True, existing=[s])
    with pytest.raises(NotClubMemberError):
        DraftSignup.submit(r, uuid4(), "usher", {}, is_club_member=False)
    with pytest.raises(DraftInvalidError):
        DraftSignup.submit(r, uuid4(), "janitor", {}, is_club_member=True)
    r.close()
    with pytest.raises(RoundClosedError):
        DraftSignup.submit(r, uuid4(), "usher", {}, is_club_member=True)


def test_withdrawn_signup_allows_a_new_one() -> None:
    r, u = rnd(), uuid4()
    s = DraftSignup.submit(r, u, "usher", {}, is_club_member=True)
    s.withdraw()
    assert s.status == "withdrawn"
    DraftSignup.submit(r, u, "mc", {}, is_club_member=True, existing=[s])


def test_pick_lifecycle() -> None:
    r = rnd()
    p = DraftPick.propose(r, uuid4(), "mc", filled={})
    assert p.status == "proposed"
    with pytest.raises(DraftPickStateError):
        p.accept()  # must be invited first
    p.invite()
    p.accept()
    p.complete()
    assert p.status == "completed"
    with pytest.raises(DraftPickStateError):
        p.decline()


def test_pick_decline_and_no_show() -> None:
    r = rnd()
    a = DraftPick.propose(r, uuid4(), "mc", {})
    a.invite()
    a.decline()
    assert a.status == "declined"
    b = DraftPick.propose(r, uuid4(), "usher", {})
    b.invite()
    b.accept()
    b.mark_no_show()
    assert b.status == "no_show"


def test_quota_per_role() -> None:
    r = rnd(needed={"usher": 2})
    DraftPick.propose(r, uuid4(), "usher", filled={"usher": 1})
    with pytest.raises(RoleFullError):
        DraftPick.propose(r, uuid4(), "usher", filled={"usher": 2})
    with pytest.raises(DraftInvalidError):
        DraftPick.propose(r, uuid4(), "cook", filled={})


# ---- ranking ------------------------------------------------------------------


def cand(uid: UUID | None = None, **kw: object) -> Candidate:
    base: dict[str, object] = {
        "user_id": uid or uuid4(),
        "availability": frozenset({"sat", "sun"}),
        "skills": frozenset({"uz", "en"}),
        "completed": 0,
        "no_show": 0,
        "recent_points": 0,
    }
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


REQ = Requirements(availability=frozenset({"sat"}), skills=frozenset({"en"}))


def test_ranking_is_deterministic_and_input_order_independent() -> None:
    cs = [cand(), cand(), cand(skills=frozenset())]
    a = rank_candidates(cs, REQ)
    b = rank_candidates(list(reversed(cs)), REQ)
    assert [r.user_id for r in a] == [r.user_id for r in b]


def test_ties_break_by_user_id() -> None:
    lo, hi = UUID(int=1), UUID(int=2)
    out = rank_candidates([cand(hi), cand(lo)], REQ)
    assert [r.user_id for r in out] == [lo, hi]


def test_no_availability_match_scores_zero() -> None:
    out = rank_candidates([cand(availability=frozenset({"mon"}))], REQ)
    assert out[0].score == 0


def test_no_show_lowers_and_completed_raises_reliability() -> None:
    good, bad, fresh = (
        cand(completed=4, no_show=0),
        cand(completed=1, no_show=3),
        cand(),
    )
    ranked = {r.user_id: r.score for r in rank_candidates([good, bad, fresh], REQ)}
    assert ranked[good.user_id] >= ranked[fresh.user_id] > ranked[bad.user_id]


def test_reliability_formula() -> None:
    c = cand(completed=3, no_show=1)
    s = rank_candidates([c], Requirements(frozenset(), frozenset()))[0].score
    assert s == pytest.approx(0.75 * 0.5)  # recency 0.5 with no recent points


def test_recent_activity_raises_score_up_to_a_cap() -> None:
    low, mid, capped, over = (
        cand(recent_points=0),
        cand(recent_points=25),
        cand(recent_points=50),
        cand(recent_points=5000),
    )
    s = {r.user_id: r.score for r in rank_candidates([low, mid, capped, over], REQ)}
    assert s[low.user_id] < s[mid.user_id] < s[capped.user_id] == s[over.user_id]


def test_empty_requirements_match_everyone() -> None:
    assert (
        rank_candidates([cand()], Requirements(frozenset(), frozenset()))[0].score > 0
    )


def test_scores_are_between_0_and_1() -> None:
    for r in rank_candidates([cand(recent_points=999, completed=9)], REQ):
        assert 0 <= r.score <= 1


# ---- points -------------------------------------------------------------------


def test_default_point_values() -> None:
    assert DEFAULT_POINTS == {
        "attended": 2,
        "volunteered": 5,
        "organized": 8,
        "draft_completed": 6,
        "no_show": -4,
        "position_held": 10,
        "peer_rating": 2,
    }


def test_no_show_writes_minus_four() -> None:
    e = entry_for("no_show", uuid4(), uuid4(), NOW)
    assert e.points == -4 and e.source_type == "no_show"


def test_settings_override_defaults() -> None:
    assert (
        entry_for("attended", uuid4(), uuid4(), NOW, settings={"attended": 3}).points
        == 3
    )


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(KeyError):
        entry_for("bribe", uuid4(), uuid4(), NOW)


def test_ledger_is_idempotent_per_source() -> None:
    ledger: list = []
    u, src = uuid4(), uuid4()
    e = entry_for("attended", u, src, NOW)
    assert add_entry(ledger, e) is True
    assert add_entry(ledger, entry_for("attended", u, src, NOW)) is False
    assert add_entry(ledger, entry_for("volunteered", u, src, NOW)) is True
    assert total(ledger) == 7


def test_total_respects_the_term_window() -> None:
    u = uuid4()
    ledger = [
        entry_for("attended", u, uuid4(), NOW - timedelta(days=40)),
        entry_for("organized", u, uuid4(), NOW),
    ]
    assert total(ledger, since=NOW - timedelta(days=1)) == 8
    assert total(ledger, until=NOW - timedelta(days=1)) == 2
    assert total(ledger) == 10


def test_leaderboard_ranks_and_masks_opted_out_students() -> None:
    a, b, c, d = (uuid4() for _ in range(4))
    rows = top(
        {a: 30, b: 30, c: 10, d: 0},
        names={a: "Ann", b: "Bob", c: "Cy", d: "Di"},
        opted_out={b},
        limit=10,
    )
    assert [r.rank for r in rows] == [1, 1, 3]  # tie shares a rank; zero points omitted
    masked = [r for r in rows if r.user_id is None]
    assert len(masked) == 1 and masked[0].display_name == "Student #1"
    assert "Bob" not in repr(rows)


def test_leaderboard_limit() -> None:
    ids = [uuid4() for _ in range(5)]
    rows = top(
        {u: i + 1 for i, u in enumerate(ids)}, dict.fromkeys(ids, "n"), set(), limit=3
    )
    assert len(rows) == 3 and rows[0].points == 5
