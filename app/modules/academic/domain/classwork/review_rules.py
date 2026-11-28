"""Pure rules of the teacher's review of a homework submission."""

import datetime as dt
from dataclasses import dataclass
from typing import Final, Literal

from app.modules.academic.domain.classwork.errors import (
    ReviewCommentRequiredError,
    ReviewCommentTooLongError,
    ReviewGradeInvalidError,
    SubmissionAlreadyGradedError,
)

ReviewStatus = Literal["pending", "returned", "graded"]
ReviewAction = Literal["grade", "return"]

# The EMIS scale, the one of ``marks`` and ``temporary_marks``.
GRADE_SCALE: Final = (2, 3, 4, 5)
TEACHER_COMMENT_MAX: Final = 2000
# A student who submits again inside this window does not notify the teacher twice.
RESUBMIT_NOTICE_WINDOW: Final = dt.timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """The review fields a grade or a return writes."""

    status: ReviewStatus
    grade: int | None
    comment: str | None


def clean_teacher_comment(value: str | None) -> str | None:
    """Trim the comment; empty is None, more than 2000 characters fails."""
    text = (value or "").strip()
    if len(text) > TEACHER_COMMENT_MAX:
        raise ReviewCommentTooLongError(params={"max": TEACHER_COMMENT_MAX})
    return text or None


def check_grade(value: int | None) -> int:
    """Return the grade when it is on the 2..5 scale.

    Raises:
        ReviewGradeInvalidError: Missing, not an integer or off the scale.
    """
    if value is None or isinstance(value, bool) or value not in GRADE_SCALE:
        raise ReviewGradeInvalidError(
            params={"min": GRADE_SCALE[0], "max": GRADE_SCALE[-1]}
        )
    return value


def decide(
    action: ReviewAction, grade: int | None, comment: str | None
) -> ReviewDecision:
    """The review a teacher's action produces.

    ``pending``, ``returned`` and ``graded`` can all be graded again; a return
    needs a comment and drops any grade.

    Raises:
        ReviewGradeInvalidError: ``grade`` without a valid grade.
        ReviewCommentRequiredError: ``return`` without a comment.
        ReviewCommentTooLongError: The comment is too long.
    """
    clean = clean_teacher_comment(comment)
    if action == "grade":
        return ReviewDecision("graded", check_grade(grade), clean)
    if clean is None:
        raise ReviewCommentRequiredError()
    return ReviewDecision("returned", None, clean)


def ensure_student_may_change(status: ReviewStatus) -> None:
    """A graded submission is final for the student.

    Raises:
        SubmissionAlreadyGradedError: The submission is graded.
    """
    if status == "graded":
        raise SubmissionAlreadyGradedError()


def should_notify_teacher(notified_at: dt.datetime | None, now: dt.datetime) -> bool:
    """True for a first submission or one more than 10 minutes after the last notice."""
    return notified_at is None or now - notified_at > RESUBMIT_NOTICE_WINDOW


def notify_effective(lesson_notify: bool | None, teacher_notify: bool) -> bool:
    """The lesson's own switch wins; without one the teacher's setting counts."""
    return teacher_notify if lesson_notify is None else lesson_notify
