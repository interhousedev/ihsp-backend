"""Errors of the lesson tutor."""

from app.shared.base_error import ForbiddenError, RateLimitedError


class TutorDisabledError(ForbiddenError):
    """The teacher turned the tutor off for this course."""

    code = "lms/tutor-disabled"
    message_key = "lms-tutor-disabled"


class TutorDailyLimitError(RateLimitedError):
    """The student asked the tutor as many times as allowed today."""

    code = "lms/tutor-daily-limit"
    message_key = "lms-tutor-daily-limit"
