"""Term validation, bell JSON and picking the current term (ADM-8, ADM-18, ACA-4)."""

import datetime as dt

from app.modules.academic.domain.schedule.errors import (
    TermBellsInvalidError,
    TermControlPeriodsInvalidError,
    TermDatesInvalidError,
    TermMovedDayInvalidError,
    TermNonStudyDayInvalidError,
)
from app.modules.academic.domain.schedule.term import (
    Bell,
    ControlPeriod,
    ControlPeriods,
    MovedDay,
    bells_from_json,
    bells_to_json,
    control_periods_from_json,
    control_periods_to_json,
    moved_days_from_json,
    pick_current_term,
    validate_term,
)
from tests.academic.schedule.builders import make_term
from tests.academic.schedule.env import default_bells

import pytest


def test_a_valid_term_passes() -> None:
    """ADM-8: the default term is valid."""
    validate_term(make_term())


def test_a_term_must_start_before_it_ends() -> None:
    """ACA-4: starts_on < ends_on."""
    term = make_term(starts_on=dt.date(2026, 12, 1), ends_on=dt.date(2026, 12, 1))

    with pytest.raises(TermDatesInvalidError):
        validate_term(term)


def test_a_period_may_appear_once_per_weekday() -> None:
    """ADM-8: bells are unique per period and weekday."""
    twice = [
        Bell(period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2]),
        Bell(period=1, start=dt.time(8, 0), end=dt.time(8, 45), weekdays=[2, 3]),
    ]

    with pytest.raises(TermBellsInvalidError):
        validate_term(make_term(bells=twice))


def test_a_bell_must_end_after_it_starts() -> None:
    """ADM-8: a period of zero length is rejected."""
    bad = [Bell(period=1, start=dt.time(9, 0), end=dt.time(9, 0), weekdays=[1])]

    with pytest.raises(TermBellsInvalidError):
        validate_term(make_term(bells=bad))


@pytest.mark.parametrize("weekday", [0, 6, 7])
def test_a_bell_must_be_on_a_school_day(weekday: int) -> None:
    """ADM-8: bells apply to weekdays 1-5; there are no Saturday bells."""
    bad = [Bell(period=1, start=dt.time(8, 0), end=dt.time(9, 0), weekdays=[weekday])]

    with pytest.raises(TermBellsInvalidError):
        validate_term(make_term(bells=bad))


def test_non_study_days_must_be_inside_the_term() -> None:
    """ADM-18: a holiday outside the term is a mistake."""
    with pytest.raises(TermNonStudyDayInvalidError):
        validate_term(make_term(non_study_days=[dt.date(2027, 1, 1)]))


@pytest.mark.parametrize("weekday", [0, 6, 7])
def test_a_moved_day_must_follow_a_weekday_from_one_to_five(weekday: int) -> None:
    """ADM-18: follows_weekday is 1-5; Saturday has no timetable to follow."""
    moved = [MovedDay(date=dt.date(2026, 11, 13), follows_weekday=weekday)]

    with pytest.raises(TermMovedDayInvalidError):
        validate_term(make_term(moved_days=moved))


def test_a_moved_day_cannot_fall_on_a_saturday() -> None:
    """ADM-18: no study day is moved onto a Saturday."""
    moved = [MovedDay(date=dt.date(2026, 11, 14), follows_weekday=1)]

    assert moved[0].date.isoweekday() == 6
    with pytest.raises(TermMovedDayInvalidError):
        validate_term(make_term(moved_days=moved))


def test_a_moved_friday_is_a_valid_moved_day() -> None:
    """ADM-18: a Monday-to-Friday date can be moved onto another weekday's timetable."""
    moved = [MovedDay(date=dt.date(2026, 11, 13), follows_weekday=1)]

    validate_term(make_term(moved_days=moved))


@pytest.mark.parametrize("day", [dt.date(2026, 11, 14), dt.date(2026, 11, 15)])
def test_a_moved_day_cannot_fall_on_a_weekend(day: dt.date) -> None:
    """ADM-18: Saturday and Sunday are not school days, so nothing moves there."""
    moved = [MovedDay(date=day, follows_weekday=1)]

    with pytest.raises(TermMovedDayInvalidError):
        validate_term(make_term(moved_days=moved))


def test_bells_are_stored_as_hours_and_minutes() -> None:
    """spec -> Term.bells: times are "08:30" in the jsonb column."""
    stored = bells_to_json(default_bells())

    assert stored[0] == {
        "period": 1,
        "start": "08:30",
        "end": "09:15",
        "weekdays": [1, 2, 3, 4, 5],
        "source": "manual",
        "emis_start": None,
        "emis_end": None,
    }
    assert bells_from_json(stored) == default_bells()


def test_saturday_bells_kept_from_before_are_left_out_on_read() -> None:
    """A Saturday bell stored earlier is skipped; the other days of it stay."""
    stored = [
        {"period": 1, "start": "08:30", "end": "09:15", "weekdays": [1, 2, 6]},
        {"period": 1, "start": "08:30", "end": "09:05", "weekdays": [6]},
    ]

    bells = bells_from_json(stored)

    assert [(b.period, b.weekdays) for b in bells] == [(1, [1, 2])]
    validate_term(make_term(bells=bells))


def test_moved_days_on_a_weekend_kept_from_before_are_left_out_on_read() -> None:
    """A moved Saturday or Sunday stored earlier is skipped, so the term saves again."""
    stored = [
        {"date": "2026-11-14", "follows_weekday": 1},
        {"date": "2026-11-15", "follows_weekday": 1},
        {"date": "2026-11-13", "follows_weekday": 1},
    ]

    moved = moved_days_from_json(stored)

    assert [m.date for m in moved] == [dt.date(2026, 11, 13)]


def test_stored_bells_are_validated_on_read() -> None:
    """CODESTYLE: jsonb columns are validated on read."""
    with pytest.raises(ValueError):
        bells_from_json(
            [{"period": 1, "start": "nope", "end": "09:15", "weekdays": [1]}]
        )


def test_the_current_term_is_the_one_containing_today() -> None:
    """ADM-8: a term that contains today wins."""
    first = make_term(starts_on=dt.date(2026, 9, 1), ends_on=dt.date(2026, 12, 25))
    second = make_term(
        half=2, starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30)
    )

    assert pick_current_term([second, first], dt.date(2026, 10, 6)) is first


def test_between_terms_the_next_term_is_current() -> None:
    """ADM-8: on a winter break the next term starts counting."""
    first = make_term(starts_on=dt.date(2026, 9, 1), ends_on=dt.date(2026, 12, 25))
    second = make_term(
        half=2, starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30)
    )

    assert pick_current_term([first, second], dt.date(2026, 12, 30)) is second


def test_after_the_last_term_the_last_term_is_current() -> None:
    """ADM-8: in summer the last term is still shown."""
    first = make_term(starts_on=dt.date(2026, 9, 1), ends_on=dt.date(2026, 12, 25))
    second = make_term(
        half=2, starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30)
    )

    assert pick_current_term([first, second], dt.date(2027, 7, 1)) is second


def test_without_terms_there_is_no_current_term() -> None:
    """ADM-8: an empty school has no term."""
    assert pick_current_term([], dt.date(2026, 10, 6)) is None


def _period(start: str, end: str) -> ControlPeriod:
    return ControlPeriod(
        start=dt.date.fromisoformat(start), end=dt.date.fromisoformat(end)
    )


def test_control_periods_are_optional() -> None:
    """A term without control weeks is valid; they are filled in later."""
    validate_term(make_term(control_periods=ControlPeriods()))
    validate_term(
        make_term(
            control_periods=ControlPeriods(final=_period("2026-12-14", "2026-12-20"))
        )
    )


def test_valid_control_periods_pass_and_list_in_order() -> None:
    """ACA-15: two midterm weeks and a final week, one after another."""
    periods = ControlPeriods(
        final=_period("2026-12-14", "2026-12-19"),
        midterm_1=_period("2026-10-20", "2026-10-25"),
        midterm_2=_period("2026-11-24", "2026-11-28"),
    )

    validate_term(make_term(control_periods=periods))

    assert [name for name, _ in periods.items()] == ["midterm_1", "midterm_2", "final"]
    assert periods.get("midterm_2") == _period("2026-11-24", "2026-11-28")
    assert ControlPeriods().get("final") is None


@pytest.mark.parametrize(
    "periods",
    [
        ControlPeriods(midterm_1=_period("2026-10-25", "2026-10-20")),
        ControlPeriods(midterm_1=_period("2026-08-25", "2026-09-02")),
        ControlPeriods(final=_period("2026-12-20", "2027-01-05")),
        ControlPeriods(
            midterm_1=_period("2026-10-20", "2026-10-25"),
            midterm_2=_period("2026-10-25", "2026-10-30"),
        ),
        ControlPeriods(
            midterm_2=_period("2026-11-24", "2026-11-28"),
            final=_period("2026-11-01", "2026-11-05"),
        ),
    ],
    ids=["reversed", "before-term", "after-term", "overlap", "out-of-order"],
)
def test_bad_control_periods_are_rejected(periods: ControlPeriods) -> None:
    """A period is reversed, outside the term, or does not follow the one before."""
    with pytest.raises(TermControlPeriodsInvalidError):
        validate_term(make_term(control_periods=periods))


def test_control_periods_round_trip_through_json() -> None:
    """Only the periods that are set are stored."""
    periods = ControlPeriods(midterm_1=_period("2026-10-20", "2026-10-25"))

    raw = control_periods_to_json(periods)

    assert raw == {"midterm_1": {"start": "2026-10-20", "end": "2026-10-25"}}
    assert control_periods_from_json(raw) == periods
    assert control_periods_from_json(None) == ControlPeriods()
    assert control_periods_from_json({}) == ControlPeriods()
