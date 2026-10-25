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
        ([5, 4], [3], [], "3.75"),
        ([5, 4], [], [5], "4.75"),
        ([5, 4], [3], [5], "4.17"),
        ([5, 4], [3, 4], [5, 5], "4.33"),
        ([], [3], [5], "4.00"),
        ([], [3], [], "3.00"),
        ([], [], [], None),
        ([5], [], [], "5.00"),
        ([4, 4, 5], [4], [], "4.17"),
    ],
)
def test_semester_mark(
    lesson: list[int], midterm: list[int], final: list[int], expected: str | None
) -> None:
    """ACA-15: the mean of the means of the types that have marks, rounded once."""
    result = grading.semester_mark(lesson, midterm, final)
    assert result == (None if expected is None else Decimal(expected))


def test_semester_mark_is_rounded_once_at_the_end() -> None:
    """The means stay exact until the last step: (4.33.. + 3) / 2 = 3.67, not 3.66."""
    assert grading.semester_mark([5, 4, 4], [3], []) == Decimal("3.67")
    assert grading.semester_mark([4, 4, 5], [3], [4]) == Decimal("3.78")


def test_present_types_lists_the_types_with_marks_in_order() -> None:
    """The mark types behind a semester mark, lesson first."""
    none, low = None, Decimal("3.00")
    assert grading.present_types(none, none, none) == ()
    assert grading.present_types(low, none, none) == ("lesson",)
    assert grading.present_types(low, low, none) == ("lesson", "midterm")
    assert grading.present_types(none, low, low) == ("midterm", "final")
    assert grading.present_types(low, low, low) == ("lesson", "midterm", "final")


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
    """ACA-22: a mark type appearing (or vanishing) changes what the mark means."""
    lesson_only = ResultSnapshot(Decimal("4.50"), Decimal("4.50"))
    partial = ResultSnapshot(Decimal("3.75"), Decimal("4.50"), Decimal("3.00"), None)
    full = ResultSnapshot(
        Decimal("4.17"), Decimal("4.50"), Decimal("3.00"), Decimal("5.00")
    )
    assert formula_switched(lesson_only, partial)
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


@pytest.mark.parametrize(
    ("lesson", "midterm", "final", "temporary", "expected"),
    [
        ([5, 4], [], [], [], None),
        ([5, 4], [], [], [3], "4.00"),
        ([], [], [], [3, 4], "3.50"),
        ([5, 4, 3], [5], [], [2, 2], "4.10"),
        ([5, 4], [3], [5], [3], "4.00"),
    ],
)
def test_semester_mark_with_temporary(
    lesson: list[int],
    midterm: list[int],
    final: list[int],
    temporary: list[int],
    expected: str | None,
) -> None:
    """Temporary marks join the lesson mean; None without any."""
    result = grading.semester_mark_with_temporary(lesson, midterm, final, temporary)

    assert result == (None if expected is None else Decimal(expected))
