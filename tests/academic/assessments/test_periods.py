"""Control weeks: which week a date belongs to, and the weeks nobody dated yet."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.assessments import periods
from tests.academic.assessments.factories import (
    GROUP,
    MATH,
    OTHER_GROUP,
    PHYSICS,
    make_assessment,
    make_term,
    period,
    standard_term,
)

import pytest

D = dt.date.fromisoformat


@pytest.mark.parametrize(
    ("kind", "day", "expected"),
    [
        ("midterm", "2026-10-19", "midterm_1"),
        ("midterm", "2026-10-24", "midterm_1"),
        ("midterm", "2026-11-25", "midterm_2"),
        ("final", "2026-12-16", "final"),
        ("midterm", "2026-12-16", None),
        ("final", "2026-10-21", None),
        ("midterm", "2026-10-25", None),
        ("other", "2026-10-21", None),
    ],
)
def test_the_week_that_holds_the_day(kind: str, day: str, expected: str | None) -> None:
    """A control date inside a week of its own kind belongs to that week."""
    got = periods.control_on(kind, D(day), [standard_term()])  # type: ignore[arg-type]
    assert got == expected


@pytest.mark.parametrize(
    ("kind", "day", "expected"),
    [
        ("midterm", "2026-10-21", "midterm_1"),
        ("midterm", "2026-10-28", "midterm_1"),
        ("midterm", "2026-11-15", "midterm_2"),
        ("midterm", "2026-12-30", "midterm_2"),
        ("final", "2026-09-05", "final"),
        ("other", "2026-10-21", None),
        ("midterm", "2027-02-01", None),
    ],
)
def test_a_date_outside_every_week_goes_to_the_nearest_week_of_its_kind(
    kind: str, day: str, expected: str | None
) -> None:
    """Teachers move controls; the slot is the closest week of that kind."""
    terms = [standard_term()]
    got = periods.infer_control(kind, D(day), terms)  # type: ignore[arg-type]
    assert got == expected


def test_a_term_without_weeks_gives_no_control() -> None:
    """Administration has not set the weeks yet."""
    assert periods.infer_control("midterm", D("2026-10-21"), [make_term()]) is None


def test_the_period_of_a_control_is_read_from_its_term() -> None:
    """The week is looked up in the term that holds the date."""
    terms = [standard_term()]

    assert periods.period_of("midterm_2", D("2026-12-01"), terms) == period(
        "2026-11-23", "2026-11-28"
    )
    assert periods.period_of(None, D("2026-12-01"), terms) is None
    assert periods.period_of("final", D("2027-06-01"), terms) is None


def _undated(
    existing: list[object] | None = None,
    subjects: tuple[UUID, ...] = (MATH, PHYSICS),
    since: str = "2026-10-01",
    until: str = "2026-12-31",
) -> list[periods.UndatedControl]:
    return periods.undated_controls(
        [standard_term()],
        subject_ids=subjects,
        group_id=GROUP,
        existing=existing or [],  # type: ignore[arg-type]
        since=D(since),
        until=D(until),
    )


def test_every_curriculum_subject_gets_every_week_until_a_teacher_dates_it() -> None:
    """3 weeks x 2 subjects, in week order."""
    found = _undated()

    assert [(c.control, c.subject_id) for c in found] == [
        ("midterm_1", MATH),
        ("midterm_1", PHYSICS),
        ("midterm_2", MATH),
        ("midterm_2", PHYSICS),
        ("final", MATH),
        ("final", PHYSICS),
    ]
    assert [c.kind for c in found] == ["midterm"] * 4 + ["final"] * 2
    assert found[0].period == period("2026-10-19", "2026-10-24")
    assert found[0].audience == (str(GROUP),)


def test_a_stored_control_takes_its_slot_whatever_its_status() -> None:
    """Planned, tentative or cancelled: the subject has an answer for that week."""
    for status in ("planned", "tentative", "cancelled"):
        taken = make_assessment(control="midterm_1", status=status)

        found = _undated([taken])

        assert ("midterm_1", MATH) not in [(c.control, c.subject_id) for c in found]
        assert ("midterm_1", PHYSICS) in [(c.control, c.subject_id) for c in found]


def test_other_groups_other_weeks_and_other_terms_do_not_take_the_slot() -> None:
    """Midterm 1 stays free: the other controls are of another group, week or term."""
    other_group = make_assessment(control="midterm_1", audience=(str(OTHER_GROUP),))
    midterm_2 = make_assessment(control="midterm_2", date=D("2026-11-25"))
    old_term = make_assessment(control="midterm_1", date=D("2026-03-10"))

    found = _undated([other_group, midterm_2, old_term], subjects=(MATH,))

    assert [c.control for c in found] == ["midterm_1", "final"]


def test_a_subgroup_control_takes_the_slot_of_the_group() -> None:
    """Any control that reaches part of the group counts as an answer."""
    subgroup = make_assessment(control="final", audience=(f"{GROUP}:1",))

    found = _undated([subgroup], subjects=(MATH,))

    assert [c.control for c in found] == ["midterm_1", "midterm_2"]


def test_only_weeks_overlapping_the_window_are_listed() -> None:
    """The Today card asks for 14 days; a running week still counts."""
    found = _undated(subjects=(MATH,), since="2026-10-22", until="2026-11-05")

    assert [c.control for c in found] == ["midterm_1"]


def test_an_undated_control_counts_down_to_the_week_start_or_today_while_it_runs() -> (
    None
):
    """Before the week: its start; during it: today; after it: the (past) start."""
    control = _undated(subjects=(MATH,))[0]

    assert control.date(D("2026-10-10")) == D("2026-10-19")
    assert control.date(D("2026-10-19")) == D("2026-10-19")
    assert control.date(D("2026-10-21")) == D("2026-10-21")
    assert control.date(D("2026-10-24")) == D("2026-10-24")
    assert control.date(D("2026-10-30")) == D("2026-10-19")


def test_the_id_of_an_undated_control_is_stable_and_unique() -> None:
    """Opening the same card twice is the same id; any difference changes it."""
    a = periods.undated_id(UUID(int=9), "midterm_1", MATH, GROUP)

    assert a == periods.undated_id(UUID(int=9), "midterm_1", MATH, GROUP)
    assert a != periods.undated_id(UUID(int=9), "midterm_2", MATH, GROUP)
    assert a != periods.undated_id(UUID(int=9), "midterm_1", PHYSICS, GROUP)
    assert a != periods.undated_id(UUID(int=9), "midterm_1", MATH, OTHER_GROUP)
    assert a != periods.undated_id(UUID(int=8), "midterm_1", MATH, GROUP)
