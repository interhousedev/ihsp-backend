"""ACA-5: odd/even weeks are derived from the dated classes EMIS sends."""

import datetime as dt
from collections.abc import Sequence

from app.modules.academic.domain.schedule.calendar import (
    parity_of_week,
    term_week,
    week_parity,
)
from app.modules.academic.domain.schedule.emis_timetable import (
    class_weekday,
    derive_slots,
)
from app.modules.academic.domain.schedule.term import MovedDay, Term
from app.shared.contracts.emis import EmisClass
from tests.academic.schedule.builders import make_term
from tests.academic.schedule.emis_builders import (
    HISTORY,
    PHYSICS,
    WEEK0,
    YULDASHEV,
    day,
    klass,
    weekly,
)

FIRST, LAST = WEEK0, WEEK0 + dt.timedelta(days=27)  # four weeks, as the sync asks
TERM = make_term(starts_on=dt.date(2026, 9, 1))  # a Tuesday: week 1 begins 31 Aug


BACKGROUND = weekly(5, 4, subject=HISTORY)  # keeps every week "observed"


def derive(
    classes: Sequence[EmisClass], term: Term = TERM, *, background: bool = True
) -> list[tuple[int, int, str, int | None, int]]:
    """The (weekday, period, parity, half, subject) of each slot the classes imply."""
    given = list(classes) + (BACKGROUND if background else [])
    found = derive_slots(term, given, FIRST, LAST)
    return [
        (s.weekday, s.period, s.parity, s.subgroup, s.latest.subject.emis_subject_id)
        for s in found
        if (s.weekday, s.period) != (5, 5) or not background
    ]


def test_the_first_monday_of_the_term_anchors_the_week_numbers() -> None:
    """ACA-5: week 1 holds the term's first day; its Monday is the anchor."""
    assert term_week(dt.date(2026, 8, 31), TERM) == 1
    assert term_week(dt.date(2026, 9, 6), TERM) == 1
    assert term_week(dt.date(2026, 9, 7), TERM) == 2
    assert term_week(WEEK0, TERM) == 6  # the first fetched week is an even one
    assert [parity_of_week(n) for n in (1, 2, 3)] == ["odd", "even", "odd"]
    assert week_parity(day(1, 3), TERM) == "odd"


def test_a_class_in_every_week_is_a_weekly_entry() -> None:
    """ACA-5: seen in each of the four weeks."""
    assert derive(weekly(2, 1)) == [(2, 2, "every", None, 101)]


def test_a_class_in_odd_weeks_only_is_an_odd_entry() -> None:
    """ACA-5: weeks 7 and 9 of the term are odd."""
    assert derive(weekly(4, weeks=(1, 3))) == [(4, 1, "odd", None, 101)]


def test_a_class_in_even_weeks_only_is_an_even_entry() -> None:
    """ACA-5: weeks 6 and 8 of the term are even."""
    assert derive(weekly(4, weeks=(0, 2))) == [(4, 1, "even", None, 101)]


def test_the_same_weeks_count_differently_from_a_later_anchor() -> None:
    """ACA-5: a term that starts a week later turns odd into even."""
    later = make_term(starts_on=dt.date(2026, 9, 7))

    assert derive(weekly(4, weeks=(1, 3)), later) == [(4, 1, "even", None, 101)]


def test_two_subjects_alternating_in_one_slot_are_an_odd_and_an_even_entry() -> None:
    """ACA-5: physics in odd weeks, history in even weeks, on the same pair."""
    classes = weekly(3, 2, weeks=(1, 3), subject=PHYSICS) + weekly(
        3, 2, weeks=(0, 2), subject=HISTORY
    )

    assert derive(classes) == [
        (3, 3, "even", None, 106),
        (3, 3, "odd", None, 102),
    ]


def test_a_week_with_a_holiday_on_that_weekday_proves_nothing() -> None:
    """ACA-5: Monday of week 7 is a non-study day, so its absence is no evidence."""
    holiday = make_term(starts_on=dt.date(2026, 9, 1), non_study_days=[day(1, 1)])

    assert derive(weekly(1, weeks=(0, 2, 3)), holiday) == [(1, 1, "every", None, 101)]


def test_a_week_without_any_class_is_not_an_observed_week() -> None:
    """ACA-5: a holiday week has no classes at all; it says nothing about parity."""
    classes = weekly(2, weeks=(0, 2)) + weekly(4, weeks=(0, 2))

    assert derive(classes, background=False) == [
        (2, 1, "every", None, 101),
        (4, 1, "every", None, 101),
    ]


def test_a_class_cancelled_in_one_week_is_still_weekly() -> None:
    """ACA-5: three of four weeks is a weekly class with one cancellation."""
    assert derive(weekly(2, weeks=(0, 1, 3))) == [(2, 1, "every", None, 101)]


def test_a_one_off_class_is_no_weekly_entry() -> None:
    """ACA-5: a midterm in one week stays a dated lesson."""
    classes = weekly(2, weeks=(0, 1, 2, 3)) + [klass(2, 4, 1, kind="midterm")]

    assert derive(classes) == [(2, 1, "every", None, 101)]


def test_halves_and_teachers_make_separate_slots() -> None:
    """ACA-5: the half and the teacher are part of what a slot is."""
    classes = weekly(1, subgroup=1) + weekly(1, subgroup=2, teacher=YULDASHEV)

    assert derive(classes) == [
        (1, 1, "every", 1, 101),
        (1, 1, "every", 2, 101),
    ]


def test_a_moved_study_day_counts_as_the_weekday_it_follows() -> None:
    """ACA-4: Friday 9 Oct follows Monday, so its classes are Monday's."""
    moved = make_term(
        starts_on=dt.date(2026, 9, 1),
        moved_days=[MovedDay(date=day(0, 5), follows_weekday=1)],
    )

    assert class_weekday(day(0, 5), moved) == 1
    assert class_weekday(day(0, 5), TERM) == 5
    # Monday's class of week 8 and the moved Friday of week 6 are one even slot.
    classes = [klass(0, 5), klass(2, 1)]
    assert derive(classes, moved) == [(1, 1, "even", None, 101)]


def test_a_moved_sunday_is_not_a_study_day_for_classes() -> None:
    """Only Monday to Friday are school days: classes on a moved Sunday are ignored."""
    moved = make_term(
        starts_on=dt.date(2026, 9, 1),
        moved_days=[MovedDay(date=day(0, 7), follows_weekday=1)],
    )

    assert class_weekday(day(0, 7), moved) is None
    # The Sunday class is ignored, exactly as without the rule: no slot comes from it.
    assert derive([klass(0, 7), klass(2, 1)], moved) == []


def test_a_class_on_a_non_study_day_keeps_its_calendar_weekday() -> None:
    """EMIS is right about its own calendar even where the term has a holiday."""
    holiday = make_term(starts_on=dt.date(2026, 9, 1), non_study_days=[day(0, 2)])

    assert class_weekday(day(0, 2), holiday) == 2


def test_sundays_have_no_slot() -> None:
    """ACA-5: there are no Sunday lessons."""
    assert class_weekday(day(0, 7), TERM) is None
    assert derive([klass(0, 7)]) == []


def test_saturdays_have_no_slot() -> None:
    """The lyceum does not study on Saturdays: EMIS classes of that day are ignored."""
    assert class_weekday(day(0, 6), TERM) is None
    assert derive([klass(week, 6) for week in range(4)]) == []
    # Even a rule that moves the Saturday onto Monday's timetable is not honoured.
    moved = make_term(
        starts_on=dt.date(2026, 9, 1),
        moved_days=[MovedDay(date=day(0, 6), follows_weekday=1)],
    )
    assert class_weekday(day(0, 6), moved) is None


def test_classes_outside_the_term_are_ignored() -> None:
    """ACA-5: the window may run past the term's end."""
    short = make_term(starts_on=dt.date(2026, 9, 1), ends_on=day(1, 7))

    assert derive(weekly(1), short) == [(1, 1, "every", None, 101)]
    assert derive_slots(short, [klass(2, 1), klass(3, 1)], FIRST, LAST) == []


def test_the_room_and_teacher_come_from_the_latest_occurrence() -> None:
    """ACA-5: the entry follows the newest class, not the oldest."""
    classes = [
        klass(0, 1, room="101"),
        klass(1, 1, room="204"),
        klass(2, 1, room="204"),
    ]
    classes.append(klass(3, 1, room="305"))

    [slot] = derive_slots(TERM, classes, FIRST, LAST)

    assert slot.latest.room == "305"
