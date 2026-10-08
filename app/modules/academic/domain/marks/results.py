"""Recomputing a subject's result from its marks (ACA-15, ACA-16, ACA-17)."""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.modules.academic.domain.marks import grading
from app.modules.academic.domain.marks.records import ResultSnapshot


def compute_subject_result(
    values_by_type: Mapping[str, Sequence[int]],
    *,
    emis_rating: int | None,
    emis_hash: str | None,
) -> ResultSnapshot:
    """Build the result row of one subject from its non-removed marks."""
    lesson = values_by_type.get("lesson", ())
    midterm = values_by_type.get("midterm", ())
    final = values_by_type.get("final", ())
    return ResultSnapshot(
        value=grading.semester_mark(lesson, midterm, final),
        lesson_avg=grading.average(lesson),
        midterm_avg=grading.average(midterm),
        final_avg=grading.average(final),
        emis_rating=emis_rating,
        marks_count=len(lesson) + len(midterm) + len(final),
        emis_hash=emis_hash,
    )


def compute_gpa(values: Sequence[int]) -> ResultSnapshot:
    """Build the semester GPA row from all non-removed marks of the semester."""
    return ResultSnapshot(value=grading.gpa(values), marks_count=len(values))


def formula_switched(old: ResultSnapshot | None, new: ResultSnapshot) -> bool:
    """Return True if the semester mark changed formula between two results (ACA-22)."""
    if old is None:
        return False
    before = grading.uses_full_formula(old.lesson_avg, old.midterm_avg, old.final_avg)
    after = grading.uses_full_formula(new.lesson_avg, new.midterm_avg, new.final_avg)
    return before != after


def drop_amount(old: Decimal | None, new: Decimal | None) -> Decimal:
    """Return how far a value fell (zero when it did not, or a side is missing)."""
    if old is None or new is None or new >= old:
        return Decimal(0)
    return old - new
