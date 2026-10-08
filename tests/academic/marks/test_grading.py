"""Grading formulas (ACA-15, ACA-16, ACA-22)."""

from decimal import Decimal

from app.modules.academic.domain.marks import grading
from app.modules.academic.domain.marks.records import ResultSnapshot
from app.modules.academic.domain.marks.results import (
    compute_gpa,
    compute_subject_result,
    drop_amount,
    formula_switched,
)

import pytest


@pytest.mark.parametrize(
    ("lesson", "midterm", "final", "expected"),
    [
        ([5, 4], [], [], "4.50"),
        ([5, 4], [3], [], "4.50"),
        ([5, 4], [], [5], "4.50"),
        ([5, 4], [3], [5], "4.17"),
        ([], [3], [5], None),
        ([5], [], [], "5.00"),
    ],
)
def test_semester_mark(
    lesson: list[int], midterm: list[int], final: list[int], expected: str | None
) -> None:
    """All three types average the averages; otherwise only the lesson average."""
    result = grading.semester_mark(lesson, midterm, final)
    assert result == (None if expected is None else Decimal(expected))


def test_gpa_is_the_mean_of_every_mark() -> None:
    """GPA over [5, 4, 3, 5] is 4.25."""
    assert grading.gpa([5, 4, 3, 5]) == Decimal("4.25")
    assert grading.gpa([]) is None


def test_average_rounds_half_up() -> None:
    """4.125 becomes 4.13, not the banker's 4.12."""
    assert grading.average([4, 4, 4, 5, 4, 4, 4, 4]) == Decimal("4.13")


def test_subject_result_counts_marks_and_keeps_rating() -> None:
    """The result row has the three averages, the mark and the EMIS fields."""
    result = compute_subject_result(
        {"lesson": [5, 4], "midterm": [3], "final": [5]},
        emis_rating=88,
        emis_hash="h",
    )
    assert result.value == Decimal("4.17")
    assert result.lesson_avg == Decimal("4.50")
    assert result.midterm_avg == Decimal("3.00")
    assert result.marks_count == 4
    assert result.emis_rating == 88
    assert result.emis_hash == "h"


def test_gpa_row_has_no_averages() -> None:
    """The GPA row stores the value and the number of marks only."""
    row = compute_gpa([5, 3])
    assert row.value == Decimal("4.00")
    assert row.lesson_avg is None
    assert row.marks_count == 2


def test_formula_switch_is_detected_both_ways() -> None:
    """ACA-22: the mark changed formula when the last type appeared, or vanished."""
    partial = ResultSnapshot(Decimal("4.50"), Decimal("4.50"), Decimal("3.00"), None)
    full = ResultSnapshot(
        Decimal("4.17"), Decimal("4.50"), Decimal("3.00"), Decimal("5.00")
    )
    assert formula_switched(partial, full)
    assert formula_switched(full, partial)
    assert not formula_switched(partial, partial)
    assert not formula_switched(None, full)


def test_drop_amount_only_counts_falls() -> None:
    """Rises, equal values and missing sides give zero."""
    assert drop_amount(Decimal("4.62"), Decimal("4.55")) == Decimal("0.07")
    assert drop_amount(Decimal("4.00"), Decimal("4.50")) == 0
    assert drop_amount(None, Decimal("4.00")) == 0
    assert drop_amount(Decimal("4.00"), None) == 0
