"""Errors of the composition endpoints."""

from app.shared.base_error import NotFoundError


class CalendarFeedNotFoundError(NotFoundError):
    """The iCal token is unknown or was replaced by a new one (WEB-6)."""

    code = "calendar/feed-not-found"
    message_key = "composition-calendar-feed-not-found"


class StudentNotFoundError(NotFoundError):
    """The user has no student record."""

    code = "composition/student-not-found"
    message_key = "composition-student-not-found"


class TeacherNotFoundError(NotFoundError):
    """The user does not exist or is not a teacher."""

    code = "composition/teacher-not-found"
    message_key = "composition-teacher-not-found"
