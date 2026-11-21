"""The Today feed: the season, its checklist, the ranked next actions, the streak.

Pure rules, no model calls. The season follows the data first (a decision or an
application in flight), then the school grade and the state of the list and the
essays. Next actions rank in three tiers: deadline urgency, then the gaps of the
current season, then the gaps of the list's fit.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

SeasonKey = Literal["explore", "build", "choose", "write", "submit", "results"]
SEASONS: Final[tuple[SeasonKey, ...]] = (
    "explore",
    "build",
    "choose",
    "write",
    "submit",
    "results",
)
MAX_NEXT: Final = 3
MAX_DEADLINES: Final = 6
URGENT_DAYS: Final = 14
"""A deadline closer than this outranks every season gap."""
DEADLINE_WINDOW_DAYS: Final = 120
MIN_CHOICES: Final = 3
"""Universities on the list before the season moves from choosing to writing."""
_DECIDED: Final = frozenset(
    {"admitted", "waitlisted", "deferred", "rejected", "enrolled"}
)
_ACTIVE: Final = frozenset({"applying", "submitted"})


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Counts of what the student has done; the input of every rule."""

    grade: str | None = None
    list_size: int = 0
    list_target: int = 6
    countries_answered: bool = False
    major_chosen: bool = False
    activities_total: int = 0
    activities_ready: int = 0
    activities_target: int = 5
    tests_planned: int = 0
    tests_received: int = 0
    tests_target: int = 2
    plans: int = 0
    plans_target: int = 3
    statement_exists: bool = False
    statement_final: bool = False
    supp_total: int = 0
    supp_final: int = 0
    docs_applicable: int = 0
    docs_done: int = 0
    tasks_overdue: int = 0
    afford_known: int = 0
    applying: int = 0
    submitted: int = 0
    decided: int = 0
    enrolled: int = 0


def auto_season(snap: Snapshot) -> SeasonKey:
    """The season implied by the data, then by the grade.

    1. Any decision on the list: results. 2. Any application in flight: submit.
    3. Grade 10 (or an unknown grade with an empty list and no activities):
    explore while nothing is built, build once there is an activity or a test.
    4. Otherwise choose until the list holds MIN_CHOICES universities, write until
    the personal statement is final, then submit.
    """
    if snap.decided:
        return "results"
    if snap.applying or snap.submitted:
        return "submit"
    nothing = (
        snap.list_size == 0 and snap.activities_total == 0 and not snap.tests_planned
    )
    if snap.grade == "grade_10" or (snap.grade is None and nothing):
        if snap.list_size >= MIN_CHOICES:
            return "choose"
        started = snap.activities_total or snap.tests_planned or snap.tests_received
        return "build" if started else "explore"
    if snap.list_size < MIN_CHOICES:
        return "choose"
    if not snap.statement_final:
        return "write"
    return "submit"


@dataclass(frozen=True, slots=True)
class Line:
    """One checklist line of a season; `progress` is "done/total" or None."""

    key: str
    done: bool
    progress: str | None
    href: str
    minutes: int


def _frac(done: int, total: int) -> str:
    return f"{min(done, total)}/{total}"


def season_lines(season: SeasonKey, s: Snapshot) -> list[Line]:
    """The checklist of a season, in the order a student should do it."""
    if season == "explore":
        return [
            Line("major", s.major_chosen, None, "/career/", 15),
            Line(
                "first_activity",
                s.activities_total >= 1,
                _frac(s.activities_total, 1),
                "/activities",
                15,
            ),
            Line(
                "test_plan",
                s.tests_planned + s.tests_received >= 1,
                _frac(s.tests_planned + s.tests_received, 1),
                "/tests",
                10,
            ),
            Line("plans", s.plans >= 1, _frac(s.plans, 1), "/plan/", 20),
        ]
    if season == "build":
        return [
            Line(
                "activities",
                s.activities_ready >= s.activities_target,
                _frac(s.activities_ready, s.activities_target),
                "/activities",
                25,
            ),
            Line(
                "tests",
                s.tests_received >= s.tests_target,
                _frac(s.tests_received, s.tests_target),
                "/tests",
                20,
            ),
            Line(
                "plans",
                s.plans >= s.plans_target,
                _frac(s.plans, s.plans_target),
                "/plan/",
                20,
            ),
            Line("tasks", s.tasks_overdue == 0, None, "/tasks", 15),
        ]
    if season == "choose":
        return [
            Line(
                "countries", s.countries_answered, None, "/chooser/search/?prefs=1", 10
            ),
            Line(
                "list",
                s.list_size >= s.list_target,
                _frac(s.list_size, s.list_target),
                "/chooser/list/",
                20,
            ),
            Line(
                "afford",
                s.list_size > 0 and s.afford_known >= s.list_size,
                _frac(s.afford_known, s.list_size) if s.list_size else None,
                "/chooser/list/",
                15,
            ),
        ]
    if season == "write":
        supp_done = s.supp_total > 0 and s.supp_final >= s.supp_total
        return [
            Line("statement", s.statement_exists, None, "/essays", 30),
            Line("statement_final", s.statement_final, None, "/essays", 40),
            Line(
                "supplements",
                supp_done,
                _frac(s.supp_final, s.supp_total) if s.supp_total else None,
                "/essays",
                40,
            ),
        ]
    if season == "submit":
        return [
            Line(
                "documents",
                s.docs_applicable > 0 and s.docs_done >= s.docs_applicable,
                _frac(s.docs_done, s.docs_applicable) if s.docs_applicable else None,
                "/documents",
                20,
            ),
            Line("tasks", s.tasks_overdue == 0, None, "/tasks", 15),
            Line(
                "submitted",
                s.list_size > 0 and s.submitted + s.decided >= s.list_size,
                _frac(s.submitted + s.decided, s.list_size) if s.list_size else None,
                "/chooser/list/",
                20,
            ),
        ]
    in_play = s.submitted + s.decided
    return [
        Line(
            "decisions",
            in_play > 0 and s.decided >= in_play,
            _frac(s.decided, in_play) if in_play else None,
            "/chooser/list/",
            10,
        ),
        Line("enrolled", s.enrolled > 0, None, "/chooser/list/", 10),
    ]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A possible next action; `tier` 0 deadline, 1 season gap, 2 fit gap."""

    tier: int
    order: int
    key: str
    title: str
    why: str
    minutes: int
    href: str
    list_entry_id: str | None = None
    kind: str = "season"
    """What it is about: a calendar source, `task`, `essay`, `season`, `afford`."""


def rank(candidates: Iterable[Candidate]) -> list[Candidate]:
    """The best MAX_NEXT: by tier, then order; one per key."""
    seen: set[str] = set()
    out: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: (c.tier, c.order)):
        if c.key in seen:
            continue
        seen.add(c.key)
        out.append(c)
    return out[:MAX_NEXT]


def streak(days: Iterable[dt.date], today: dt.date) -> tuple[int, bool, list[bool]]:
    """Run of consecutive active days, whether today counts, the last seven days.

    A run that ended yesterday is still alive: today may yet be done.
    """
    active = set(days)
    today_done = today in active
    cursor = today if today_done else today - dt.timedelta(days=1)
    run = 0
    while cursor in active:
        run += 1
        cursor -= dt.timedelta(days=1)
    last7 = [today - dt.timedelta(days=6 - i) in active for i in range(7)]
    return run, today_done, last7


def urgent(days_left: int) -> bool:
    """Whether a deadline is close enough to outrank the season gaps."""
    return days_left <= URGENT_DAYS
