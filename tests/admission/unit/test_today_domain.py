"""The rules of the Today feed: season, checklist, ranking and streak."""

import datetime as dt

from app.modules.admission.domain.today import (
    Candidate,
    Snapshot,
    auto_season,
    rank,
    season_lines,
    streak,
)

TODAY = dt.date(2026, 11, 21)


def test_season_follows_decisions_then_applications_then_grade() -> None:
    assert auto_season(Snapshot(decided=1, applying=1)) == "results"
    assert auto_season(Snapshot(applying=1)) == "submit"
    assert auto_season(Snapshot(submitted=1, list_size=5)) == "submit"
    assert auto_season(Snapshot(grade="grade_10")) == "explore"
    assert auto_season(Snapshot(grade="grade_10", activities_total=1)) == "build"
    assert auto_season(Snapshot(grade="grade_10", list_size=3)) == "choose"
    assert auto_season(Snapshot(grade="grade_11", list_size=1)) == "choose"
    assert auto_season(Snapshot(grade="grade_11", list_size=4)) == "write"
    final = Snapshot(grade="grade_11", list_size=4, statement_final=True)
    assert auto_season(final) == "submit"
    assert auto_season(Snapshot()) == "explore"


def test_every_season_has_lines_with_progress_and_hrefs() -> None:
    snap = Snapshot(list_size=2, activities_ready=5, tests_received=1)
    for season in ("explore", "build", "choose", "write", "submit", "results"):
        lines = season_lines(season, snap)
        assert lines and all(ln.href.startswith("/") and ln.minutes > 0 for ln in lines)
    by_key = {ln.key: ln for ln in season_lines("build", snap)}
    assert by_key["activities"].done and by_key["activities"].progress == "5/5"
    assert not by_key["tests"].done and by_key["tests"].progress == "1/2"
    assert by_key["tasks"].done


def _c(tier: int, order: int, key: str) -> Candidate:
    return Candidate(tier, order, key, key, "why", 10, "/x")


def test_rank_orders_by_tier_dedupes_and_caps_at_three() -> None:
    out = rank(
        [
            _c(2, 0, "fit"),
            _c(1, 1, "gap2"),
            _c(1, 0, "gap1"),
            _c(0, 50, "late"),
            _c(0, 10, "soon"),
            _c(0, 10, "soon"),
        ]
    )
    assert [c.key for c in out] == ["soon", "late", "gap1"]


def test_streak_counts_a_run_ending_today_or_yesterday() -> None:
    d = dt.timedelta
    run, done, last7 = streak({TODAY, TODAY - d(days=1), TODAY - d(days=2)}, TODAY)
    assert (run, done) == (3, True)
    assert last7 == [False] * 4 + [True] * 3
    assert streak({TODAY - d(days=1), TODAY - d(days=2)}, TODAY)[:2] == (2, False)
    assert streak({TODAY - d(days=2)}, TODAY)[:2] == (0, False)
    assert streak(set(), TODAY) == (0, False, [False] * 7)
