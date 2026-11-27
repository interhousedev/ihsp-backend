"""Errors of the engagement features."""

from app.shared.base_error import ForbiddenError, NotFoundError, ValidationFailedError


class ReviewItemNotFoundError(NotFoundError):
    """The review item does not exist or belongs to someone else."""

    code = "lms/review-item-not-found"
    message_key = "lms-engage-review-item-not-found"


class QuestNotFoundError(NotFoundError):
    """The quest does not exist in this course."""

    code = "lms/quest-not-found"
    message_key = "lms-engage-quest-not-found"


class QuestDatesInvalidError(ValidationFailedError):
    """The quest ends before it starts or runs longer than 31 days."""

    code = "lms/quest-dates-invalid"
    message_key = "lms-engage-quest-dates-invalid"


class SectionLockedError(ForbiddenError):
    """The section opens after the previous one reaches the mastery threshold."""

    code = "lms/section-locked"
    message_key = "lms-engage-section-locked"


class LevelSchemeInvalidError(ValidationFailedError):
    """The curve, the tiers or the names of a level scheme are unusable."""

    code = "lms/level-scheme-invalid"
    message_key = "lms-engage-level-scheme-invalid"


class LevelSchemeNotFoundError(NotFoundError, LookupError):
    """The level scheme does not exist."""

    code = "lms/level-scheme-not-found"
    message_key = "lms-engage-level-scheme-not-found"
