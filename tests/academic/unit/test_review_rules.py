"""Pure rules of the teacher's homework review."""

import datetime as dt

from app.modules.academic.domain.classwork.errors import (
    ReviewCommentRequiredError,
    ReviewCommentTooLongError,
    ReviewGradeInvalidError,
    SubmissionAlreadyGradedError,
)
from app.modules.academic.domain.classwork.review_rules import (
    ReviewDecision,
    check_grade,
    decide,
    ensure_student_may_change,
    notify_effective,
    should_notify_teacher,
)

import pytest

NOW = dt.datetime(2026, 10, 9, 12, tzinfo=dt.UTC)


@pytest.mark.parametrize("grade", [2, 3, 4, 5])
def test_grades_on_the_scale_pass(grade: int) -> None:
    assert check_grade(grade) == grade


@pytest.mark.parametrize("grade", [None, 0, 1, 6, True])
def test_grades_off_the_scale_fail(grade: int | None) -> None:
    with pytest.raises(ReviewGradeInvalidError):
        check_grade(grade)


def test_grade_keeps_an_optional_trimmed_comment() -> None:
    assert decide("grade", 5, None) == ReviewDecision("graded", 5, None)
    assert decide("grade", 4, "  good ") == ReviewDecision("graded", 4, "good")
    assert decide("grade", 4, "   ") == ReviewDecision("graded", 4, None)


def test_return_needs_a_comment_and_drops_the_grade() -> None:
    assert decide("return", 5, " redo ") == ReviewDecision("returned", None, "redo")
    with pytest.raises(ReviewCommentRequiredError):
        decide("return", None, None)
    with pytest.raises(ReviewCommentRequiredError):
        decide("return", None, "  ")


def test_grade_without_a_grade_fails() -> None:
    with pytest.raises(ReviewGradeInvalidError):
        decide("grade", None, "fine")


def test_comment_over_2000_characters_fails() -> None:
    assert decide("grade", 5, "x" * 2000).comment == "x" * 2000
    with pytest.raises(ReviewCommentTooLongError):
        decide("grade", 5, "x" * 2001)
    with pytest.raises(ReviewCommentTooLongError):
        decide("return", None, "x" * 2001)


def test_only_a_graded_submission_is_final_for_the_student() -> None:
    ensure_student_may_change("pending")
    ensure_student_may_change("returned")
    with pytest.raises(SubmissionAlreadyGradedError):
        ensure_student_may_change("graded")


def test_teacher_is_notified_once_per_ten_minutes() -> None:
    assert should_notify_teacher(None, NOW)
    assert not should_notify_teacher(NOW - dt.timedelta(minutes=10), NOW)
    assert should_notify_teacher(NOW - dt.timedelta(minutes=10, seconds=1), NOW)


def test_lesson_switch_overrides_the_teacher_setting() -> None:
    assert notify_effective(None, True) is True
    assert notify_effective(None, False) is False
    assert notify_effective(False, True) is False
    assert notify_effective(True, False) is True
