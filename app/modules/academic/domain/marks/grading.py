"""Grading formulas: averages, semester mark and GPA (ACA-15, ACA-16)."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    """Round to 2 places, halves up."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _mean(values: Sequence[int]) -> Decimal | None:
    """Return the exact mean or None for no values."""
    if not values:
        return None
    return Decimal(sum(values)) / Decimal(len(values))


def average(values: Sequence[int]) -> Decimal | None:
    """Mean rounded to 2 places; None for no values."""
    mean = _mean(values)
    return None if mean is None else _round(mean)


def semester_mark(
    lesson: Sequence[int], midterm: Sequence[int], final: Sequence[int]
) -> Decimal | None:
    """ACA-15: mean of the lesson, midterm and final means, else the lesson mean.

    The three means are combined only when all three types have marks. They are
    combined unrounded, so the result is rounded once.
    """
    lesson_mean = _mean(lesson)
    midterm_mean = _mean(midterm)
    final_mean = _mean(final)
    if lesson_mean is None:
        return None
    if midterm_mean is None or final_mean is None:
        return _round(lesson_mean)
    return _round((lesson_mean + midterm_mean + final_mean) / Decimal(3))


def gpa(all_marks: Sequence[int]) -> Decimal | None:
    """ACA-16: average of all marks of the semester (all subjects, all types)."""
    return average(all_marks)


def uses_full_formula(
    lesson_avg: Decimal | None,
    midterm_avg: Decimal | None,
    final_avg: Decimal | None,
) -> bool:
    """Return True when the semester mark averages all three mark types."""
    return None not in (lesson_avg, midterm_avg, final_avg)
