"""Rules of assessments: countdown, reminders, statuses and duplicates."""

import datetime as dt
from uuid import uuid4

from app.modules.academic.domain.assessments import rules
from tests.academic.assessments.factories import (
    GROUP,
    MATH,
    OTHER_GROUP,
    PHYSICS,
    make_assessment,
    make_new,
)

import pytest

TODAY = dt.date(2026, 10, 14)


@pytest.mark.parametrize(
    ("day", "left"),
    [("2026-10-14", 0), ("2026-10-15", 1), ("2026-10-21", 7), ("2026-10-10", -4)],
)
def test_days_left_counts_from_today(day: str, left: int) -> None:
    """The countdown is negative once the control is past."""
    assert rules.days_left(dt.date.fromisoformat(day), TODAY) == left


@pytest.mark.parametrize(
    ("day", "offset"),
    [
        ("2026-10-21", 7),
        ("2026-10-17", 3),
        ("2026-10-15", 1),
        ("2026-10-14", None),
        ("2026-10-16", None),
        ("2026-10-18", None),
        ("2026-10-22", None),
    ],
)
def test_reminders_fire_exactly_7_3_and_1_days_before(
    day: str, offset: int | None
) -> None:
    """A planned control is reminded only on the three offsets."""
    assessment = make_assessment(date=dt.date.fromisoformat(day))

    assert rules.reminder_offset(assessment, TODAY) == offset


@pytest.mark.parametrize("status", ["tentative", "cancelled"])
def test_unconfirmed_and_cancelled_controls_are_never_reminded(status: str) -> None:
    """A date nobody confirmed may be wrong; a cancelled control does not happen."""
    assessment = make_assessment(date=dt.date(2026, 10, 21), status=status)

    assert rules.reminder_offset(assessment, TODAY) is None


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("teacher", "planned"),
        ("admin", "planned"),
        ("emis", "tentative"),
        ("head_student", "tentative"),
    ],
)
def test_who_plans_and_who_only_suggests(source: str, status: str) -> None:
    """Teachers and Administration plan; EMIS and head students suggest."""
    assert rules.initial_status(source) == status  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current", "requested", "changed", "expected"),
    [
        ("tentative", None, True, "planned"),
        ("tentative", None, False, "tentative"),
        ("tentative", "planned", False, "planned"),
        ("tentative", "cancelled", True, "cancelled"),
        ("planned", None, True, "planned"),
        ("planned", "cancelled", False, "cancelled"),
        ("cancelled", "planned", False, "planned"),
        ("cancelled", None, True, "cancelled"),
    ],
)
def test_status_after_a_staff_edit(
    current: str, requested: str | None, changed: bool, expected: str
) -> None:
    """Editing a tentative control confirms it; an explicit status wins."""
    got = rules.status_after_edit(
        current, requested, changed=changed  # type: ignore[arg-type]
    )
    assert got == expected


def test_a_group_key_covers_its_subgroups() -> None:
    """Whole group vs subgroup overlap; two different subgroups do not."""
    group = str(GROUP)

    assert rules.audiences_overlap([group], [f"{group}:1"])
    assert rules.audiences_overlap([f"{group}:2"], [group])
    assert rules.audiences_overlap([f"{group}:1"], [f"{group}:1", f"{group}:2"])
    assert not rules.audiences_overlap([f"{group}:1"], [f"{group}:2"])
    assert not rules.audiences_overlap([group], [str(OTHER_GROUP)])
    assert not rules.audiences_overlap([], [group])


def test_the_same_control_a_few_days_apart_is_a_duplicate() -> None:
    """Same subject, kind and audience within a week: already known."""
    existing = make_assessment(date=dt.date(2026, 10, 21))

    assert rules.is_duplicate(make_new(date=dt.date(2026, 10, 21)), existing)
    assert rules.is_duplicate(make_new(date=dt.date(2026, 10, 28)), existing)
    assert not rules.is_duplicate(make_new(date=dt.date(2026, 10, 29)), existing)


def test_other_subjects_kinds_and_audiences_are_not_duplicates() -> None:
    """Any difference in subject, kind or audience makes it a new control."""
    existing = make_assessment()

    assert not rules.is_duplicate(make_new(subject_id=PHYSICS), existing)
    assert not rules.is_duplicate(make_new(kind="final"), existing)
    assert not rules.is_duplicate(make_new(audience=(str(OTHER_GROUP),)), existing)
    assert existing.subject_id == MATH


def test_the_same_control_week_is_a_duplicate_even_far_apart() -> None:
    """A teacher moved the date of midterm 1; the suggestion is still the same slot."""
    existing = make_assessment(date=dt.date(2026, 10, 21), control="midterm_1")
    far = make_new(date=dt.date(2026, 11, 20), control="midterm_1")
    other_slot = make_new(date=dt.date(2026, 11, 20), control="midterm_2")

    assert rules.is_duplicate(far, existing)
    assert not rules.is_duplicate(other_slot, existing)


def test_the_same_control_name_in_another_term_is_not_a_duplicate() -> None:
    """Midterm 1 of spring is not midterm 1 of autumn."""
    existing = make_assessment(date=dt.date(2026, 10, 21), control="midterm_1")
    spring = make_new(date=dt.date(2027, 3, 10), control="midterm_1")

    assert not rules.is_duplicate(spring, existing)


def test_a_cancelled_control_still_counts_as_known() -> None:
    """A dismissed suggestion must not come back."""
    existing = make_assessment(status="cancelled", id=uuid4())

    assert rules.is_duplicate(make_new(), existing)
