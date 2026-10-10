"""Weekly timetable slots, derived from the dated classes EMIS sends (ACA-1, ACA-5).

EMIS does not know "odd" or "even" weeks: it lists the classes of each date. A slot
(weekday, pair, half, subject, teacher) that shows up in every observed week is a
weekly entry; one that shows up only in odd weeks or only in even weeks is an
odd/even entry. Weeks are counted from the term's first Monday (``term_week``).

Everything here is pure; the use case feeds it the classes it fetched.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.academic.domain.schedule.calendar import (
    effective_weekday,
    parity_of_week,
    term_week,
)
from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import WeekParity
from app.shared.contracts.emis import EmisClass

SlotKey = tuple[int, int, int | None, int, object]


@dataclass(frozen=True, slots=True)
class DerivedSlot:
    """A weekly entry the observed classes imply; ``latest`` has its subject etc."""

    weekday: int
    period: int
    parity: WeekParity
    subgroup: int | None
    latest: EmisClass


def class_weekday(day: dt.date, term: Term) -> int | None:
    """The weekday whose timetable the class belongs to (a moved day follows another).

    EMIS may list a class on a date the term calls a non-study day; the class then
    keeps its calendar weekday. None for a Saturday or a Sunday that follows no
    weekday: the lyceum has no lessons then, so EMIS classes on those days are ignored.
    """
    weekday = effective_weekday(day, term) or day.isoweekday()
    return weekday if weekday in SCHOOL_DAYS else None


def derive_slots(
    term: Term, classes: Sequence[EmisClass], first: dt.date, last: dt.date
) -> list[DerivedSlot]:
    """Return the weekly slots that the classes of first..last imply.

    A slot seen in some weeks only is classified by the weeks it was missing from:

    * missing from none of the weeks that had a study day on its weekday: every week;
    * present in exactly the odd (or exactly the even) such weeks, with the other
      parity absent: odd (even) weeks only;
    * otherwise present in more than half of them: every week (a class was cancelled);
      else a one-off, which is no weekly slot (it stays a dated lesson).
    """
    in_term = [c for c in classes if term.starts_on <= c.date <= term.ends_on]
    observed = {term_week(c.date, term) for c in in_term}
    opportunities = _opportunities(term, first, last)
    found: dict[SlotKey, list[EmisClass]] = defaultdict(list)
    for item in sorted(in_term, key=lambda c: c.date):
        weekday = class_weekday(item.date, term)
        if weekday is not None:
            found[_key(weekday, item)].append(item)
    slots: list[DerivedSlot] = []
    for key, items in found.items():
        weekday = key[0]
        witnesses = {w for w in observed if (w, weekday) in opportunities}
        present = {term_week(c.date, term) for c in items} & witnesses
        parity = _parity(present, witnesses)
        if parity is not None:
            slots.append(DerivedSlot(weekday, key[1], parity, key[2], items[-1]))
    slots.sort(key=lambda s: (s.weekday, s.period, s.subgroup or 0, s.parity))
    return slots


def _key(weekday: int, item: EmisClass) -> SlotKey:
    teacher = item.teacher
    who: object = None
    if teacher is not None:
        who = teacher.emis_id or (
            teacher.last_name.casefold(),
            teacher.first_name.casefold(),
        )
    return (
        weekday,
        item.pair_number + 1,
        item.subgroup,
        item.subject.emis_subject_id,
        who,
    )


def _opportunities(term: Term, first: dt.date, last: dt.date) -> set[tuple[int, int]]:
    """The (week, weekday) pairs that had at least one study day in first..last."""
    pairs: set[tuple[int, int]] = set()
    day = first
    while day <= last:
        weekday = effective_weekday(day, term)
        if weekday is not None and term.starts_on <= day <= term.ends_on:
            pairs.add((term_week(day, term), weekday))
        day += dt.timedelta(days=1)
    return pairs


def _parity(present: set[int], witnesses: set[int]) -> WeekParity | None:
    if not present:
        return None
    if present == witnesses:
        return "every"
    parities = {parity_of_week(w) for w in present}
    if len(parities) == 1:
        (only,) = parities
        same = {w for w in witnesses if parity_of_week(w) == only}
        if present == same:
            return only
    return "every" if len(present) * 2 > len(witnesses) else None
