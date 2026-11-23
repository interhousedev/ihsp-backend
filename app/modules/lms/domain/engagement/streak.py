"""School-week streaks: Mon-Fri required, weekends a bonus, earned freezes.

Days are calendar dates in Asia/Tashkent (no DST), so the streak is a pure
function of the set of days with any XP and of today.

Rules:
- an active weekday or weekend day adds one to the streak;
- an inactive weekend day is a rest day and changes nothing;
- an inactive past weekday spends a freeze when one is held (and the streak is
  running), otherwise the streak drops to zero;
- today never breaks the streak while it is still open;
- every Mon-Fri week with all five weekdays active earns a freeze, at most
  `MAX_FREEZES` are held.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal

MAX_FREEZES: Final = 2
HISTORY_DAYS: Final = 400

DayState = Literal["done", "freeze", "missed", "pending", "bonus"]


@dataclass(frozen=True, slots=True)
class WeekDay:
    """One day of the current Mon-Sun week."""

    date: date
    state: DayState


@dataclass(frozen=True, slots=True)
class Streak:
    """The streak of a learner as of today."""

    current: int
    best: int
    freezes: int
    today_done: bool
    at_risk: bool
    week: tuple[WeekDay, ...]


def is_weekday(day: date) -> bool:
    """Return True for Monday to Friday."""
    return day.weekday() < 5


def week_start(day: date) -> date:
    """Return the Monday of the day's week."""
    return day - timedelta(days=day.weekday())


def compute_streak(active_days: Iterable[date], today: date) -> Streak:
    """Walk the history day by day and return the streak as of today."""
    active = {d for d in active_days if d <= today}
    floor = today - timedelta(days=HISTORY_DAYS)
    start = min((d for d in active if d >= floor), default=today)
    run = best = freezes = 0
    states: dict[date, DayState] = {}
    day = start
    while day <= today:
        weekday = is_weekday(day)
        if day in active:
            run += 1
            states[day] = "done" if weekday else "bonus"
        elif day == today or not weekday:
            states[day] = "pending"
        elif freezes > 0 and run > 0:
            freezes -= 1
            states[day] = "freeze"
        else:
            run = 0
            states[day] = "missed"
        best = max(best, run)
        if day.weekday() == 4 and all(
            day - timedelta(days=n) in active for n in range(5)
        ):
            freezes = min(MAX_FREEZES, freezes + 1)
        day += timedelta(days=1)
    monday = week_start(today)
    week = tuple(
        WeekDay(
            date=d,
            state=states.get(d, "missed" if is_weekday(d) and d < today else "pending"),
        )
        for d in (monday + timedelta(days=n) for n in range(7))
    )
    today_done = today in active
    return Streak(
        current=run,
        best=best,
        freezes=freezes,
        today_done=today_done,
        at_risk=is_weekday(today) and not today_done and run > 0,
        week=week,
    )


def active_days_in_week(active_days: Iterable[date], today: date) -> int:
    """Return how many days of today's Mon-Sun week had activity."""
    monday = week_start(today)
    return sum(1 for d in set(active_days) if monday <= d <= today)
