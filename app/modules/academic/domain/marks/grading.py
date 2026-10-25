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
    """ACA-15: the mean of the means of the mark types that have marks.

    Lesson, midterm and final means count as soon as their type has a mark, so a
    mark with a midterm but no final yet is the mean of two means. They are combined
    unrounded, so the result is rounded once.
    """
    means = [
        mean
        for mean in (_mean(lesson), _mean(midterm), _mean(final))
        if mean is not None
    ]
    if not means:
        return None
    return _round(sum(means) / Decimal(len(means)))


def semester_mark_with_temporary(
    lesson: Sequence[int],
    midterm: Sequence[int],
    final: Sequence[int],
    temporary: Sequence[int],
) -> Decimal | None:
    """The semester mark as if the temporary lesson marks were in EMIS already.

    None when there are no temporary marks: the plain `semester_mark` stands then.
    """
    if not temporary:
        return None
    return semester_mark([*lesson, *temporary], midterm, final)


def gpa(all_marks: Sequence[int]) -> Decimal | None:
    """ACA-16: average of all marks of the semester (all subjects, all types)."""
    return average(all_marks)


def present_types(
    lesson_avg: Decimal | None,
    midterm_avg: Decimal | None,
    final_avg: Decimal | None,
) -> tuple[str, ...]:
    """Return the mark types that have marks, in the order lesson, midterm, final."""
    averages = (("lesson", lesson_avg), ("midterm", midterm_avg), ("final", final_avg))
    return tuple(name for name, value in averages if value is not None)
